# Eneo tool runtime

Eneo's bundled, isolated MCP provider. It is a small Bun service. Operator
documentation lives in `docs/deployment/TOOL_RUNTIME.md`.

- `POST /mcp/compute` is a stateless Streamable HTTP MCP endpoint (JSON
  responses) exposing `run_javascript`.
- `POST /mcp/file-analysis` exposes `inspect_table`, `query_table` and
  `assert_table` over signed Eneo attachment URLs. It fetches only from the
  origin Eneo sends in `X-Eneo-File-Origin`.
- `POST /mcp/charts` (`create_chart`) returns PNG charts as MCP image blocks,
  from inline series or a CSV/XLSX source file.
- `POST /mcp/file-creation` (`create_document`, DOCX or PDF from Markdown,
  optionally into a Word template; `create_spreadsheet`, XLSX) returns the
  file as an embedded resource that Eneo saves in the conversation.
- `GET /health/live` and `GET /health/ready` are the health endpoints.

## Layout

| Path                         | Purpose                                                  |
| ---------------------------- | -------------------------------------------------------- |
| `src/main.ts`                | Entrypoint: environment config, HTTP server              |
| `src/server.ts`              | Bearer check, Origin refusal, body/result bounds, MCP    |
| `src/sandbox.ts`             | One child process per job (empty env, watchdog, tmpdir)  |
| `src/child.ts`               | Child entrypoint                                         |
| `src/tools/compute/`         | QuickJS engine, limits and the tool definition           |
| `src/tools/tabular/`         | Download policy, parsed-sheet cache, DuckDB/XLSX engines |
| `src/tools/documents/`       | Markdown parser and DOCX, PDF and XLSX renderers         |
| `src/tools/charts/`          | Chart spec, SVG drawing and resvg rasterization          |
| `src/tools/files/`           | Signed Eneo file references shared by all file inputs    |

The compute engine was ported from eneo-tools (`packages/compute`, commit
`585b271`). The tabular engines were ported from `packages/tabular` and
`packages/files` at the same commit, with workspaces, handles and the database
replaced by per-call signed URLs and a disposable cache. The renderers come
from `packages/document-export`, returning embedded resources instead of
download links. New tools belong here only when they need platform-owned
isolation. Domain integrations stay separate MCP services.

## Development

Run these inside the devcontainer:

```bash
cd /workspace/tool-runtime
bun install
bun run test
bun run typecheck
```

In the devcontainer, run it in its own terminal next to the backend and
frontend:

```bash
cd /workspace/tool-runtime
bun run dev
```

The devcontainer sets `TOOL_RUNTIME_URL=http://localhost:3010` and a shared dev
`TOOL_RUNTIME_TOKEN` for both processes, so **Admin > Tools > MCP servers**
offers the servers built into Eneo right away. Tabular analysis fetches from whatever the backend's
`FILE_REFERENCE_BASE_URL` (or `PUBLIC_ORIGIN`) points at, so that address must
be reachable from inside the devcontainer. In development the runtime shares the
devcontainer's network. Only the deployment overlay puts it on an internal
network without egress.

Sandbox children are confined with [landrun](https://github.com/zouuup/landrun)
(Linux Landlock) when it is installed. The image builds it in; for local runs
and the confinement tests, build it once from the host, where Docker is
available:

```bash
cd tool-runtime
bun run build:landrun   # writes bin/landrun (ignored by git)
```

Without it children run unconfined and the confinement tests are skipped. The
start-up log line reports what is enforced (`"confinement":{"files":true,"tcp":true}`).

## Configuration

| Variable              | Default | Notes                                  |
| --------------------- | ------- | -------------------------------------- |
| `TOOL_RUNTIME_TOKEN`  | none    | Required, at least 32 characters        |
| `PORT`                | 3010    |                                        |
| `MAX_CONCURRENCY`     | 16      | Concurrent MCP requests before 429     |
| `COMPUTE_TIMEOUT_MS`  | 5000    | Script deadline (100 to 30000)         |
| `COMPUTE_MEMORY_MB`   | 64      | Script memory limit (8 to 256)         |
| `TOOL_RUNTIME_FILE_ORIGINS` | none | Optional comma-separated limit on Eneo's file origin |
| `TABULAR_CONCURRENCY` | 2       | DuckDB children running at once        |
| `TABULAR_MAX_UPLOAD_MB` | 20    | Largest attachment downloaded          |
| `TABULAR_CACHE_MB`    | 256     | Parsed-sheet cache budget on `/tmp`    |
| `TABULAR_CACHE_TTL_SECONDS` | 1800 | How long parsed sheets stay on `/tmp` (60 to 86400) |
| `TOOL_RUNTIME_REQUIRE_CONFINEMENT` | false | Refuse to start or run jobs unless children are confined |
| `DOCUMENT_ORGANISATION_NAME` | none | Name in generated document footers |

Releases are versioned by `VERSION` and published by
`.github/workflows/tool_runtime_image.yml` from develop. A published version tag
is never moved, so bump `VERSION` for any change.
