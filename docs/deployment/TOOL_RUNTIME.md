# Bundled tool runtime

The tool runtime is an optional container shipped with Eneo. It serves
Eneo-maintained MCP tools from an isolated process, never from the backend.
It has two endpoints:

- `/mcp/compute`: `run_javascript`, restricted compute over JSON. It is added
  as an ordinary MCP server.
- `/mcp/tabular`: `inspect_table`, `query_table` and `assert_table` over
  attached CSV and XLSX files. It is added as the provider of the **Tabular
  analysis** capability (`tabular_analysis`, "Analysera tabelldata" in Swedish).

## TL;DR

- Optional. Eneo runs normally without it.
- It has no database, no console, no operator API and no registration sync.
  Eneo registers it through **Admin > Tools** like any other MCP server.
- The only credential is a shared bearer (`TOOL_RUNTIME_TOKEN`). Eneo reads it
  from its settings at connect time, so it is never stored in the database.
- Tools go through the normal review, per-tool enablement, space enablement and
  per-call approval. Adding the bundled server grants nobody anything.

## What the compute tool can and cannot do

`run_javascript` runs model-written JavaScript over bounded JSON input and
returns bounded JSON output.

- Each call runs in a fresh QuickJS (WebAssembly) runtime. It sees only `input`
  and `console`, with no network, filesystem, timers, imports, host APIs or
  environment, and keeps no state between calls.
- Each call runs in a separate child process that inherits nothing but `PATH`
  and a private temporary directory. The bearer token never reaches it.
- Limits: 20,000 characters of code, 64 KiB input, 256 KiB result, 100 log
  lines, 64 MB memory and a 5 s script deadline. An external watchdog kills
  the child at the whole-job deadline.
- The container runs on an `internal` network that only the backend and worker
  join. It has no route out even if guest code escaped both the engine and
  the child.

## What the tabular tools can and cannot do

The model passes the signed URL of an attachment, exactly as Eneo put it in the
conversation. The runtime then works as follows:

1. It accepts only URLs of the form
   `<origin>/api/v1/files/<id>/original/download/?token=…` whose origin is
   listed in `TOOL_RUNTIME_FILE_ORIGINS`. Any other URL is refused before a
   request is made.
2. It downloads the file on every call. Eneo checks the token each time, so a
   revoked or expired link stops working at once. Downloads are capped at 20
   MiB and 15 s, pin the resolved address and re-validate redirects.
3. It parses the file in a sandbox child. CSV must be UTF-8. XLSX goes through
   a zip-bomb guard and is converted to one CSV per sheet. At most 20 sheets
   and 64 MiB expanded.
4. It caches the parsed sheets on local disk for 30 minutes, keyed by tenant,
   user and the downloaded bytes' hash. The cache never replaces the download
   in step 2, so it can never grant access. A miss simply parses again.
5. It runs the model's SQL in a separate sandbox child with a fresh DuckDB.
   Before any model SQL is prepared, DuckDB's external access, extensions and
   configuration are locked. Only a single `SELECT` is accepted, as determined
   by DuckDB's own parser. Queries are limited to 500 rows, 10 s, 256 MB and
   1 thread.

The tabular server forwards the user's identity, which the cache needs.
At most `TOOL_RUNTIME_TABULAR_CONCURRENCY` (default 2) DuckDB children run at
once; other calls wait. Formulas are read as their cached values. Writing
spreadsheets is not part of this endpoint.

## Enable it

1. Generate a token: `openssl rand -hex 32`.
2. In `.env`, set the image digest and the token:

   ```bash
   ENEO_TOOL_RUNTIME_IMAGE=ghcr.io/eneo-ai/eneo-tool-runtime:0.1.0-eneo.1@sha256:<digest>
   TOOL_RUNTIME_TOKEN=<token>
   ```

3. In `env_backend.env`, set the same token and the runtime URL:

   ```bash
   TOOL_RUNTIME_URL=http://tool-runtime:3010
   TOOL_RUNTIME_TOKEN=<token>
   # Needed for tabular analysis: signed file links must be reachable from the runtime.
   FILE_REFERENCE_BASE_URL=http://backend:8000
   ```

   The overlay sets `TOOL_RUNTIME_FILE_ORIGINS=http://backend:8000` on the
   runtime. It must match `FILE_REFERENCE_BASE_URL`. Set it to an empty value
   to serve compute only.

4. Start it with the overlay and profile:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tool-runtime.yml \
     --profile tool-runtime up -d
   ```

5. In **Admin > Tools > MCP servers**, choose **Add bundled compute**. Eneo
   tests the connection and discovers the tool. Review it, then enable the
   server in the spaces that should use it.
6. In **Admin > Tools > Functions**, choose **Use bundled provider** on the
   **Tabular analysis** card. If no provider is active yet, it becomes the
   default. Then enable the capability in spaces and assistants. The
   `tabular_analysis` permission is granted to the predefined User, AI
   Configurator and Owner roles. Custom roles need it added.

## Rotate the token

Set a new `TOOL_RUNTIME_TOKEN` in both `.env` and `env_backend.env` and
recreate `tool-runtime`, `backend` and `worker`. Nothing in the database
changes.

## Footprint

These figures were measured on the reference image (`0.1.0-eneo.1`, linux/arm64,
Docker Desktop):

| Condition                                      | Memory   |
| ---------------------------------------------- | -------- |
| Idle                                           | ~69 MiB  |
| 16 concurrent CPU-bound calls (default limit)  | ~580 MiB |
| After the burst                                | ~69 MiB  |

Each concurrent compute call costs about 32 MiB for its child process. A
tabular query child can use up to 256 MB for DuckDB, which is why only
`TOOL_RUNTIME_TABULAR_CONCURRENCY` of them run at once. The overlay caps the
container at 2 GiB, 2 CPUs and 256 processes. `/tmp` is a 512 MiB tmpfs that
holds job scratch space and the 256 MiB parsed-sheet cache, and it counts
towards memory. If you raise either concurrency setting, raise `mem_limit` with
it. Requests beyond `TOOL_RUNTIME_MAX_CONCURRENCY` get HTTP 429 and surface in
chat as a tool error.

## Failure behaviour

If the runtime is stopped or unreachable, the tool call fails and the assistant
answers without it. Chat is otherwise unaffected. Script errors, timeouts and
oversized results come back to the model as `ok: false` results, so it can
correct its code.
