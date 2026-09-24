# Bundled tool runtime

The tool runtime is an optional container shipped with Eneo. It serves
Eneo-maintained MCP tools from an isolated process, never from the backend.
Today it serves one tool: `run_javascript` (restricted compute over JSON).

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
   ```

4. Start it with the overlay and profile:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.tool-runtime.yml \
     --profile tool-runtime up -d
   ```

5. In **Admin > Tools > MCP servers**, choose **Add bundled compute**. Eneo
   tests the connection and discovers the tool. Review it, then enable the
   server in the spaces that should use it.

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

Each concurrent call costs about 32 MiB for its child process. The overlay caps
the container at 1 GiB, 2 CPUs and 256 processes. If you raise
`TOOL_RUNTIME_MAX_CONCURRENCY`, raise `mem_limit` with it. Requests beyond the
limit get HTTP 429 and surface in chat as a tool error.

## Failure behaviour

If the runtime is stopped or unreachable, the tool call fails and the assistant
answers without it. Chat is otherwise unaffected. Script errors, timeouts and
oversized results come back to the model as `ok: false` results, so it can
correct its code.
