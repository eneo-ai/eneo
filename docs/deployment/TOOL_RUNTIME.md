# Bundled tool runtime

The tool runtime is an optional container shipped with Eneo. It serves
Eneo-maintained MCP tools from an isolated process, never from the backend.
It has four endpoints:

- `/mcp/compute`: `run_javascript`, restricted compute over JSON. It is added
  as an ordinary MCP server.
- `/mcp/file-analysis`: `inspect_table`, `query_table` and `assert_table` over
  attached CSV and XLSX files (more formats will follow). It is added as the
  provider of the **Ask a file** capability (`file_analysis`, "Fråga fil" in
  Swedish).
- `/mcp/file-creation`: `create_document`, which renders Word (DOCX) or PDF
  from Markdown, optionally into a Word template from the conversation, and
  `create_spreadsheet`, which builds XLSX workbooks with named sheets and typed
  cells. It provides **Create a file** (`file_creation`).
- `/mcp/charts`: `create_chart`, which draws bar, line, pie and scatter charts
  as PNG images. It is added as an ordinary MCP server.

## Chaining tools without copying data

Large data moves between tools as Eneo files, never through the model:

1. `query_table` with `export: true` writes its complete result (up to 200,000
   rows) as a CSV file. Eneo saves it as a visible download and hands the model
   a signed reference URL for it in the same answer.
2. `create_spreadsheet` takes that URL as a sheet `source`, and `create_chart`
   takes it as its `source` with a label column and value columns. Each
   downloads the file with the same checks as the tabular tools: Eneo's origin
   only, and access checked on every download.

The providers share nothing but those Eneo-owned files and links, so any of
them can be replaced by an external provider that follows the same MCP
conventions. The same-turn reference needs a streaming chat; over the
non-streaming API, the reference arrives on the next turn. Charts are PNG
images; interactive MCP Apps widgets are not supported.

## TL;DR

- Optional. Eneo runs normally without it.
- It has no database, no console, no operator API and no registration sync.
  Eneo registers it through **Admin > Tools** like any other MCP server.
- The only credential is a shared bearer (`TOOL_RUNTIME_TOKEN`). Eneo reads it
  from its settings at connect time, so it is never stored in the database.
- Tools go through the normal review, per-tool enablement, space enablement and
  per-call approval. Adding the bundled server grants nobody anything.

## Isolation: what keeps one conversation's data from another

The runtime is one container shared by every tenant and conversation, so the
separation between jobs is what matters for sensitive files. It rests on these
layers:

1. **Eneo decides which files a tool call may name.** A tool call can only
   carry signed links to the files of its own conversation (its attachments
   and the files its tools created). Eneo refuses any other file link in the
   arguments before the runtime is contacted, so a link from another
   conversation is never fetched, whoever put it there.
2. **The runtime holds no credentials and no data of its own.** It has no
   database and no signing key, and with the overlay no route to Postgres,
   Redis or the internet. It can only redeem the links Eneo handed it.
3. **Each job runs in its own process, confined before it starts.** The
   launcher ([landrun](https://github.com/zouuup/landrun), Linux Landlock)
   restricts the child to its private directory and the files that one job
   was given. It cannot open another job's files, the parsed-sheet cache
   entries of other users, or the server process's environment, and it has no
   TCP at all. This holds even if a crafted file or query takes over one of the
   engines (DuckDB, the renderers, the JavaScript engine).
4. **The container limits what an escape could reach.** Read-only root
   filesystem, no capabilities, no privilege escalation and an internal
   network (see the overlay).

Layer 3 needs a host kernel with Landlock: Linux 5.13 or later for files, 6.7
or later for the TCP restriction. Docker's default seccomp profile allows it.
The start-up log line states what is enforced:

```json
{"event":"listening", "confinement":{"files":true,"tcp":true}}
```

On a host that cannot confine jobs the runtime still works, with layers 1, 2
and 4 only. Where sensitive or classified files are handled, set
`TOOL_RUNTIME_REQUIRE_CONFINEMENT=true` in `.env`: the runtime then refuses to
start, and to run any job, unless files are confined.

What this does not cover:

- A kernel exploit from inside a confined job. A sandboxed runtime such as
  gVisor (`runtime: runsc` on the service) adds that layer where the host
  offers it. It protects the host, not one conversation from another, so it
  complements the confinement above and does not replace it.
- Parsed sheets stay in `/tmp` (memory-backed) for follow-up questions, 30
  minutes by default. With confinement, only the server process and the jobs
  that query that same file can read them.
  `TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS` shortens that, down to 60 seconds,
  and expired entries are removed on a timer.
- Deployments that do not use the overlay (another orchestrator, the
  development container) must provide layer 4 themselves: no egress, a
  read-only root filesystem and no capabilities.

Setting a security classification on the built-in server in **Admin > Tools**
is the administrator's statement that this deployment may handle files of that
level. Check the start-up line and the points above before raising it.

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

## What the file analysis tools can and cannot do

The model passes the signed URL of an attachment, exactly as Eneo put it in the
conversation. The runtime then works as follows:

1. It accepts only URLs of the form
   `<origin>/api/v1/files/<id>/original/download/?token=…`. The origin must be
   the one Eneo sends with the call (`X-Eneo-File-Origin`, taken from
   `FILE_REFERENCE_BASE_URL`), never one chosen by the model. Any other URL is
   refused before a request is made. `TOOL_RUNTIME_FILE_ORIGINS` optionally
   pins the allowed origins on the runtime side as well.
2. It downloads the file on every call. Eneo checks the token each time, so a
   revoked or expired link stops working at once. Downloads are capped at 20
   MiB and 15 s, pin the resolved address and re-validate redirects.
3. It parses the file in a sandbox child. CSV must be UTF-8. XLSX goes through
   a zip-bomb guard and is converted to one CSV per sheet. At most 20 sheets
   and 64 MiB expanded.
4. It caches the parsed sheets on local disk for 30 minutes
   (`TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS`), keyed by tenant, user and the
   downloaded bytes' hash. The cache never replaces the download in step 2, so
   it can never grant access. A miss simply parses again, and expired entries
   are removed on a timer.
5. It runs the model's SQL in a separate sandbox child with a fresh DuckDB.
   Before any model SQL is prepared, DuckDB's external access, extensions and
   configuration are locked. Only a single `SELECT` is accepted, as determined
   by DuckDB's own parser. Queries are limited to 500 rows, 10 s, 256 MB and
   1 thread.

The file analysis server forwards the user's identity, which the cache needs.
At most `TOOL_RUNTIME_TABULAR_CONCURRENCY` (default 2) DuckDB children run at
once; other calls wait. Formulas are read as their cached values. Writing
spreadsheets is not part of this endpoint.

## Word templates

`create_document` takes an optional `template`: the signed reference of a
`.docx` the user attached in the chat or an administrator attached to the
assistant. The runtime downloads it under the same policy as other
attachments, refuses macro-enabled files, and renders the content into it:
the template keeps its styles, headers, footers, numbering and page setup. A
paragraph in the template reading `{{content}}` marks where the content goes;
without one the template's body is replaced. Eneo checks the result like any
other generated document.

## Upgrading the runtime

The runtime's tools are Eneo's own code, so they are trusted like a built-in
provider's. A completion lists the running runtime's catalog (cached per
backend process for five minutes) and keeps only the administrator's per-tool
decisions (enabled, display name) from the stored rows, so a new runtime image
is in use as soon as it runs; nobody has to press **Sync tools**. Pressing it
still refreshes the stored rows the admin pages show, and the changes are
approved without review.

## Revising a created file

`create_document` and `create_spreadsheet` take an optional `revises`: the
signed reference of a file the tool created earlier in the conversation. The
model passes the complete revised content; the new file replaces the earlier
one, reuses its filename, and a Word file keeps its layout and the template it
was made from (the earlier file serves as the template). The result names the
file it replaces so the answer can say so. Eneo keeps both files, like an image
and its edited variation.

## Created documents and spreadsheets

The renderers run in a sandbox child and return the file inside the tool result
as a standard MCP embedded resource. The runtime keeps no copy and serves no
download links. Eneo then does the following:

1. It admits the file only because the server provides `file_creation`
   (DOCX, PDF, XLSX). The same resource from any other server stays an
   ordinary result.
2. It checks the bytes: OOXML packages must be well-formed, bounded and free of
   macros, embedded objects and externally loaded content. PDFs must be
   complete and free of script, launch actions and embedded files.
3. It saves the document as a File in the conversation, with extracted text and
   its exact original. The user downloads it from a chip under the answer. It
   survives reloads, follows the conversation's access rules and is deleted with
   the conversation.

Spreadsheets store text as text: a value starting with `=` is never written as a
formula. Formula writing, templates and editing existing files are not part of
this release. `DOCUMENT_ORGANISATION_NAME` sets the name shown in document
footers.

## Enable it

1. Generate a token: `openssl rand -hex 32`.
2. In `.env`, set the image digest and the token:

   ```bash
   ENEO_TOOL_RUNTIME_IMAGE=ghcr.io/eneo-ai/eneo-tool-runtime:0.1.0-eneo.1@sha256:<digest>
   TOOL_RUNTIME_TOKEN=<token>
   ```

   The overlay hands this token to the runtime, the backend and the worker,
   and points the backend at `http://tool-runtime:3010`. Nothing goes into
   `env_backend.env` for the runtime itself.

3. For file analysis and Word templates, the runtime must be able to reach Eneo's signed file
   links. In `env_backend.env`:

   ```bash
   FILE_REFERENCE_BASE_URL=http://backend:8000
   ```

   Eneo tells the runtime this origin on every call. To have the runtime
   enforce it as well, also set `TOOL_RUNTIME_FILE_ORIGINS=http://backend:8000`
   in `.env`.

4. Start it with the overlay and profile:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tool-runtime.yml \
     --profile tool-runtime up -d
   ```

5. In **Admin > Tools > MCP servers**, open **Add MCP Server** and pick
   **Compute** or **Charts** under *Built into Eneo*. Eneo tests the connection
   and discovers the tools. Review them, then enable the server in the spaces
   that should use it.
6. In **Admin > Tools > Functions**, the **Ask a file** and **Create a file**
   cards offer the provider built into Eneo: **Turn on** adds it and makes it
   the default when no provider is active yet. Then enable the capabilities in
   spaces and assistants. Their permissions (`file_analysis`, `file_creation`)
   are granted to the predefined User, AI Configurator and Owner roles. Custom
   roles need them added.

## Rotate the token

Set a new `TOOL_RUNTIME_TOKEN` in `.env` and recreate `tool-runtime`,
`backend` and `worker`. Nothing in the database changes.

## Footprint

These figures were measured on the reference image (`0.1.0-eneo.1`, linux/arm64,
Docker Desktop):

| Condition                                      | Memory   |
| ---------------------------------------------- | -------- |
| Idle                                           | ~69 MiB  |
| 16 concurrent CPU-bound calls (default limit)  | ~580 MiB |
| After the burst                                | ~69 MiB  |

Each concurrent compute call costs about 32 MiB for its child process. A
tabular query child can use up to 256 MB for DuckDB. Such children, and the
document renderers, share `TOOL_RUNTIME_TABULAR_CONCURRENCY` slots, so only
that many run at once. The overlay caps the
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
