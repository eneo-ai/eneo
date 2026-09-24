# Eneo tool runtime

Eneo's bundled, isolated MCP provider. It is a small Bun service. Operator
documentation lives in `docs/deployment/TOOL_RUNTIME.md`.

- `POST /mcp/compute` is a stateless Streamable HTTP MCP endpoint (JSON
  responses) exposing `run_javascript`.
- `GET /health/live` and `GET /health/ready` are the health endpoints.

## Layout

| Path                         | Purpose                                                  |
| ---------------------------- | -------------------------------------------------------- |
| `src/main.ts`                | Entrypoint: environment config, HTTP server              |
| `src/server.ts`              | Bearer check, Origin refusal, body/result bounds, MCP    |
| `src/sandbox.ts`             | One child process per job (empty env, watchdog, tmpdir)  |
| `src/child.ts`               | Child entrypoint                                         |
| `src/tools/compute/`         | QuickJS engine, limits and the tool definition           |

The compute engine was ported from eneo-tools (`packages/compute`, commit
`585b271`). New tools belong here only when they need platform-owned
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
offers **Add bundled compute** right away. In development the runtime shares the
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

Releases are versioned by `VERSION` and published by
`.github/workflows/tool_runtime_image.yml` from develop. A published version tag
is never moved, so bump `VERSION` for any change.
