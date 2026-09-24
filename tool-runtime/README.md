# Eneo tool runtime

Eneo's bundled, isolated MCP provider. It is a small Bun service. Operator
documentation lives in `docs/deployment/TOOL_RUNTIME.md`.

- `POST /mcp/compute` is a stateless Streamable HTTP MCP endpoint (JSON
  responses) exposing `run_javascript`.
- `POST /mcp/tabular` exposes `inspect_table`, `query_table` and
  `assert_table` over signed Eneo attachment URLs. It is served only when
  `TOOL_RUNTIME_FILE_ORIGINS` is set.
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

The compute engine was ported from eneo-tools (`packages/compute`, commit
`585b271`). The tabular engines were ported from `packages/tabular` and
`packages/files` at the same commit, with workspaces, handles and the database
replaced by per-call signed URLs and a disposable cache. New tools belong here only when they need platform-owned
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
offers **Add bundled compute** right away. It also allows
`http://localhost:8123` and `http://host.docker.internal:8123` as file origins.
For tabular analysis, the backend's `FILE_REFERENCE_BASE_URL` must be one of
them. In development the runtime shares the
devcontainer's network. Only the deployment overlay puts it on an internal
network without egress.

## Configuration

| Variable              | Default | Notes                                  |
| --------------------- | ------- | -------------------------------------- |
| `TOOL_RUNTIME_TOKEN`  | none    | Required, at least 32 characters        |
| `PORT`                | 3010    |                                        |
| `MAX_CONCURRENCY`     | 16      | Concurrent MCP requests before 429     |
| `COMPUTE_TIMEOUT_MS`  | 5000    | Script deadline (100 to 30000)         |
| `COMPUTE_MEMORY_MB`   | 64      | Script memory limit (8 to 256)         |
| `TOOL_RUNTIME_FILE_ORIGINS` | none | Comma-separated origins of Eneo's signed file links; enables `/mcp/tabular` |
| `TABULAR_CONCURRENCY` | 2       | DuckDB children running at once        |
| `TABULAR_MAX_UPLOAD_MB` | 20    | Largest attachment downloaded          |
| `TABULAR_CACHE_MB`    | 256     | Parsed-sheet cache budget on `/tmp`    |

Releases are versioned by `VERSION` and published by
`.github/workflows/tool_runtime_image.yml` from develop. A published version tag
is never moved, so bump `VERSION` for any change.
