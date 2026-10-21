# Bundled tool runtime: operator guide

The tool runtime is an isolated container included in the standard Eneo
deployment. It serves the Eneo-maintained MCP tools behind five Functions, from
its own process and network, never from the backend:

| Endpoint | Function | Tools |
| --- | --- | --- |
| `/mcp/compute` | **Compute** (`compute`, "Beräkning") | `run_javascript` |
| `/mcp/file-analysis` | **Ask a file** (`file_analysis`, "Fråga fil") | `inspect_table`, `query_table`, `assert_table` |
| `/mcp/file-creation` | **Create a file** (`file_creation`, "Skapa fil") | `create_document`, `edit_document`, `fill_template`, `create_spreadsheet` |
| `/mcp/charts` | **Charts** (`charts`, "Diagram") | `create_chart` |
| `/mcp/forecast` | **Forecast** (`forecast`, "Prognos") | `create_forecast` |

This guide covers deploying, configuring, upgrading, diagnosing and omitting
the runtime. Other pages own the rest:

- Why the runtime exists as a separate service, and how it relates to the
  loopback servers and external MCP servers:
  [Tools and MCP Architecture](https://docs.eneo.ai/dev/docs/tool-architecture)
  (`frontend/apps/docs-site/src/content/docs/tool-architecture.mdx`).
- What it defends against and how, layer by layer:
  [Tool Runtime Security](https://docs.eneo.ai/dev/docs/tool-runtime-security)
  (`frontend/apps/docs-site/src/content/docs/tool-runtime-security.mdx`).
- What the tools do, how files chain between them, templates, exports and the
  interactive views users see: [Functions](https://docs.eneo.ai/dev/guides/capabilities)
  (`frontend/apps/docs-site/src/content/guides/capabilities.mdx`).
- Interactive tool views and their host permissions: [MCP_APPS.md](MCP_APPS.md).
- Developing the runtime itself: `tool-runtime/README.md`.

## TL;DR

- Included by default. Functions remain opt-in; ordinary Eneo runs without it.
- It has no database, no console, no operator mutation API and no registration
  sync. Eneo registers it through **Admin > Tools** like any other MCP server.
- The only credential is a shared bearer (`TOOL_RUNTIME_TOKEN`). Eneo reads it
  from its settings at connect time, so it is never stored in the database.
- Its tools and views are Eneo's own code and follow the deployed image
  without a sync or an approval. Adding the bundled server grants nobody
  anything: per-tool enablement, space enablement, role permissions and
  per-call approval still apply.
- Frontend, backend and runtime share one version and source revision. There
  is no separate runtime version.

## Deploy, upgrade and roll back

The image publication workflow (`build_and_push_images.yml`) publishes a
complete bundle only after component checks and a combined smoke test pass.

Download `release.env` and `release.json` from the selected GitHub release, or
the completed workflow artifact for a development build. The JSON manifest
records the version, revision and three immutable image digests. Take
deployment templates from that recorded source revision as well. The
environment file supplies those references to Compose, including the backend
image used by workers and initialization jobs. After configuring the usual
environment files:

```bash
python3 setup.py
docker compose --env-file .env --env-file release.env up -d
```

The setup helper creates a strong runtime token only when absent, protects
`.env` with mode 0600, and preserves existing settings without printing
secrets. Without a bundle, `python3 setup.py --version X.Y.Z` selects one
explicit shared version. Digest-pinned bundles are preferred.

The standard stack starts the runtime and connects the backend and general
worker to it over `tool_runtime_net`. File references default to
`http://backend:8000`. Override `FILE_REFERENCE_BASE_URL` in Compose's `.env`
when needed; `TOOL_RUNTIME_FILE_ORIGINS` follows it unless explicitly
overridden. The setup helper carries existing runtime URL, token and
file-origin overrides from `env_backend.env` into `.env` when absent there.
Thereafter these Compose values take precedence; keep overrides in `.env`.

Upgrade by replacing both bundle files together and recreating application
services. Roll back using the previous complete bundle, observing the
release's normal database rollback constraints. The bundle itself needs no
database migration; the migrations of the release it carries apply as usual.
External deployment automation must consume the bundle; floating image tags
cannot change atomically.

### Migrating from the first runtime release

For installations that added the runtime through the earlier overlay: remove
the old runtime image pin from `.env`, adopt the complete bundle, and remove
the extra overlay and profile from your Compose commands.
`docker-compose.tool-runtime.yml` remains an empty compatibility shim for one
release. Registrations, external providers, permissions and activation
decisions are preserved. Installing the service does not enable Functions.

### Omitting the runtime

```bash
docker compose --env-file .env --env-file release.env \
  -f docker-compose.yml -f docker-compose.without-tools.yml up -d
```

Stop an existing `tool-runtime` container first when adopting the opt-out. Do
not enable the `disabled-tool-runtime` profile by hand. Backend startup and
readiness never depend on runtime health; without the runtime the Functions it
would serve show **Not enabled in this deployment** under **Admin > Tools**.

## Turning Functions on

In **Admin > Tools > Functions**, turn on **Ask a file**, **Create a file**,
**Charts**, **Compute** or **Forecast** (**Built into Eneo**), then make each
Function available on the spaces and assistants that should use it. Roles still need
the matching permission; active external providers are not replaced
automatically. The [Functions guide](https://docs.eneo.ai/dev/guides/capabilities)
covers the administrator workflow.

### After upgrading to a release that adds Charts

Apply migrations `202610081100` and `202610091100`, then add **Built into
Eneo** under **Admin > Tools > Functions > Charts** and activate it. Enable
**Charts** on the space and assistant. The predefined Owner role holds the
`charts` permission, on upgrade as on a new install; an administrator opts
other roles in. The migrations only widen the capability constraints and
preserve all existing settings. Existing bundled general chart servers keep
their current attachments and can coexist with the new provider; retire them
through the admin UI after configuring the Function to avoid offering the same
tool twice.

### After upgrading to a release that adds Compute

Apply migration `202610131300`, then add **Built into Eneo** under
**Admin > Tools > Functions > Compute** and activate it. Enable **Compute** on
the space and assistant. The migration grants the `compute` permission to the
predefined Owner role only, as new installs do. A bundled compute server added
earlier from the MCP servers tab keeps its attachments and coexists with the
new provider; retire it once the Function is configured.

### After upgrading to a release that adds Forecast

Mount a checkpoint as described in [The forecast model](#the-forecast-model)
and apply migration `202610201000`, then add **Built into Eneo** under
**Admin > Tools > Functions > Forecast** and activate it. Enable **Forecast**
on the space and assistant, or allow it for the personal assistant under
**Admin > Personal assistant > Tools**. The migration grants the `forecast` permission to the predefined Owner role only,
as new installs do; an administrator opts other roles in.

## Configuration

Compose maps the deployment `.env` to the runtime's own variable names. The
backend and worker read `TOOL_RUNTIME_URL`, `TOOL_RUNTIME_TOKEN` and
`FILE_REFERENCE_BASE_URL` directly.

| In `.env` | Runtime variable | Default | Meaning |
| --- | --- | --- | --- |
| `TOOL_RUNTIME_TOKEN` | `TOOL_RUNTIME_TOKEN` | generated by `setup.py` | Shared bearer, at least 32 characters |
| `TOOL_RUNTIME_URL` | | `http://tool-runtime:3010` | Where the backend and worker reach the runtime |
| `FILE_REFERENCE_BASE_URL` | | `http://backend:8000` | Origin of the signed file links the runtime downloads from |
| `TOOL_RUNTIME_FILE_ORIGINS` | `TOOL_RUNTIME_FILE_ORIGINS` | follows `FILE_REFERENCE_BASE_URL` | Origins the runtime will download from at all |
| `TOOL_RUNTIME_REQUIRE_CONFINEMENT` | `TOOL_RUNTIME_REQUIRE_CONFINEMENT` | `false` | Refuse to start or run jobs unless children are confined |
| `TOOL_RUNTIME_MAX_CONCURRENCY` | `MAX_CONCURRENCY` | 16 | Active tool calls |
| `TOOL_RUNTIME_MAX_QUEUE` | `MAX_QUEUE` | 32 | Waiting tool calls |
| `TOOL_RUNTIME_MAX_QUEUE_PER_GROUP` | `MAX_QUEUE_PER_GROUP` | 8 | Waiting calls per tenant |
| `TOOL_RUNTIME_TABULAR_CONCURRENCY` | `TABULAR_CONCURRENCY` | 2 | Native-engine jobs (DuckDB, Office renderers, charts) at once |
| `TOOL_RUNTIME_TABULAR_CACHE_MB` | `TABULAR_CACHE_MB` | 256 | Budget for original bytes and parsed sheets on `/tmp` |
| `TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS` | `TABULAR_CACHE_TTL_SECONDS` | 1800 | Idle lifetime of cached bytes and sheets (60 to 86400) |
| `TOOL_RUNTIME_DOCUMENT_ORGANISATION_NAME` | `DOCUMENT_ORGANISATION_NAME` | unset | Name shown in generated document footers |

Variables without a `.env` mapping in the reference stack
(`DOCUMENT_PDF_CONCURRENCY`, `COMPUTE_TIMEOUT_MS`, `COMPUTE_MEMORY_MB`,
`TABULAR_MAX_UPLOAD_MB`, `DOCUMENT_MAX_CONTENT_CHARS`) keep the defaults in
`tool-runtime/README.md`; set them on the service in a Compose override if you
need to.

The forecast engine reads `FORECAST_MODEL_PATH`, `FORECAST_MODEL_NAME`,
`FORECAST_CONCURRENCY` and `FORECAST_THREADS`; see
[The forecast model](#the-forecast-model).

`BUNDLED_CATALOG_TTL_SECONDS` on the backend (default 300) controls how long a
backend process caches the runtime's tool catalog; see
[Upgrading the runtime](#upgrading-the-runtime).

## The forecast model

The `/mcp/forecast` endpoint runs Timestral, a time-series model from Mistral AI,
on the runtime's CPU. The image holds the engine (CPU-only torch and the Apache-2.0
`timestral` library, pinned in `tool-runtime/scripts/requirements-forecast.txt`)
but no model weights. You provide a checkpoint, and the runtime never downloads one.

The weights are published under Mistral's "Modified MIT" licence, which does not
grant any rights to an organisation whose global consolidated monthly revenue,
or its employer's, exceeds USD 20 million. Check that your organisation, and
whoever operates Eneo for it, may use the checkpoint, or obtain a commercial
licence from Mistral. Keep the licence file with the weights.

1. Download one checkpoint at a pinned revision to the host, for example
   Timestral 28M:

   ```bash
   hf download mistralai/Timestral-28M config.json model.safetensors LICENSE \
     --revision 49b26409ac87b5935539a5d8ffe7f397b720db47 \
     --local-dir /srv/eneo/models/timestral-28m
   ```

   `hf` comes with `pip install huggingface_hub`. The directory must hold
   `config.json` and `model.safetensors`.

2. Mount it read-only into the runtime in a Compose override, and name it for
   users:

   ```yaml
   services:
     tool-runtime:
       environment:
         FORECAST_MODEL_NAME: "Timestral 28M"
       volumes:
         - /srv/eneo/models/timestral-28m:/models/forecast:ro
   ```

3. Recreate `tool-runtime`.

| Runtime variable | Default | Meaning |
| --- | --- | --- |
| `FORECAST_MODEL_PATH` | `/models/forecast` | Checkpoint directory inside the container |
| `FORECAST_MODEL_NAME` | `Timestral` | How users see the model named |
| `FORECAST_CONCURRENCY` | 1 | Forecasts at a time; each runs its own Python sidecar |
| `FORECAST_THREADS` | 2 | CPU threads one forecast may use |

Without a checkpoint, or with a directory that is not a Timestral checkpoint, a
forecast fails with `MODEL_UNAVAILABLE` and every other tool keeps working.
While the checkpoint files are missing, **Admin > Tools** says so; see
[Diagnostics](#diagnostics). A larger checkpoint (Timestral 123M or 209M) fits the same steps; give the
runtime more memory and threads before you raise `FORECAST_CONCURRENCY`.

## Isolation checklist

The runtime is one container shared by every tenant and conversation, so the
separation between jobs is what protects sensitive files. The full model is in
[Tool Runtime Security](https://docs.eneo.ai/dev/docs/tool-runtime-security).
What the operator contributes:

1. **Keep it on an internal network.** The reference stack puts it on
   `tool_runtime_net` (`internal: true`) with only the backend and worker. It
   must have no route to PostgreSQL, Redis or the internet.
2. **Keep the container hardened.** The reference stack sets a read-only root
   filesystem, `cap_drop: ALL`, `no-new-privileges`, a `noexec` tmpfs on
   `/tmp`, and memory, CPU and process limits. Deployments on another
   orchestrator must provide the same.
3. **Check that jobs are confined.** Each job runs in a child process confined
   with Linux Landlock through [landrun](https://github.com/zouuup/landrun).
   That needs a host kernel of 5.13 or later for files and 6.7 or later for
   the TCP restriction, not filtered by a seccomp profile. The start-up log
   line states what is enforced:

   ```json
   {"event":"listening", "port":3010, "endpoints":[…], "confinement":{"files":true,"tcp":true}}
   ```

   On a host that cannot confine jobs the runtime still works with its other
   layers. Where sensitive or classified files are handled, set
   `TOOL_RUNTIME_REQUIRE_CONFINEMENT=true`: the runtime then refuses to start,
   and to run any job, unless files are confined.
4. **Pin the file origin.** `FILE_REFERENCE_BASE_URL` must be an address only
   the runtime and trusted MCP servers can reach, and
   `TOOL_RUNTIME_FILE_ORIGINS` should name it (the reference stack does this
   by default).
5. **Decide on cache residency.** Original bytes and parsed sheets stay in the
   memory-backed `/tmp` for follow-up questions, 30 minutes idle by default.
   `TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS` shortens that, down to 60 seconds.

Sandboxed container runtimes (gVisor, Kata Containers) add a layer between the
container and the host kernel. Eneo has not run the tool runtime under one, so
they are outside the supported configuration; a deployment that tries one does
so untested.

Setting a security classification on the built-in server in **Admin > Tools**
is the administrator's statement that this deployment may handle files of that
level. Check the start-up line and the points above before raising it.

## Upgrading the runtime

The runtime's tools and views are Eneo's own code, so they are trusted like a
built-in provider's. A completion lists the running runtime's catalog, cached
per backend process for `BUNDLED_CATALOG_TTL_SECONDS` (300 by default; a
development install sets it to a few seconds so a rebuilt view reaches chats
at once), and keeps only the administrator's per-tool decisions (enabled,
display name) from the stored rows. A new runtime image is therefore in use as
soon as it runs; nobody has to press **Sync tools**. Pressing it still
refreshes the stored rows the admin pages show. Each catalog change is written
to the audit log as a change made by the system.

## Diagnostics

**Admin > Tools** shows status even after providers have been registered:
missing configuration, unreachable service, rejected credentials, unknown or
mismatched versions, unavailable confinement and file-origin problems.
Version and revision mismatches warn while calls remain allowed. A reachable
file origin proves only TCP connectivity, not access to a particular file.

Backend probes call the runtime's private `GET /diagnostics` (bearer required)
with a three-second deadline and cache the answer for 30 seconds. They never
gate tool execution or ordinary chat. The public `GET /health/live` and
`GET /health/ready` endpoints report liveness only.

The diagnostics also list, under `unavailable`, the endpoints that cannot run
now. `forecast` is listed while the sidecar's Python or the checkpoint files
(`config.json` and `model.safetensors` in `FORECAST_MODEL_PATH`) are missing.
The runtime checks on each diagnostics request, so a checkpoint copied into
the mounted directory later counts without a restart. **Admin > Tools** then
offers Forecast as unavailable, saying "This function needs a model that your
operator adds to the tool runtime." (reason `model_missing`); it raises no
warning on the runtime card. Calls are not refused: a forecast fails with
`MODEL_UNAVAILABLE` and every other tool keeps working.

Structured runtime events report request ID, tool, queue and execution time,
cache revalidation, transferred bytes and cancellation. They omit tokens,
signed URLs, file contents and model arguments.

## Capacity, caching and scheduling

Original bytes and parsed sheets share a 256 MiB cache and a 30-minute idle
lifetime (`TOOL_RUNTIME_TABULAR_CACHE_MB`,
`TOOL_RUNTIME_TABULAR_CACHE_TTL_SECONDS`). Every use revalidates the current
signed link with Eneo; cache failures never authorize stale data. Entries are
scoped to user and tenant, pinned during jobs, and discarded on restart.

Defaults are 16 active calls, two native-engine jobs and two PDF renders at a
time. Waiting tenants take turns, borrowing idle capacity. Each replica
schedules locally; there are no persistent quotas and no distributed
scheduling. `TOOL_RUNTIME_MAX_QUEUE` permits 32 waiting calls and
`TOOL_RUNTIME_MAX_QUEUE_PER_GROUP` eight per tenant. A full queue returns a
busy tool result; excess HTTP intake gets HTTP 429. Queue time counts toward
the call deadline. Cancellation removes waiting jobs, aborts downloads and
kills active child process groups before cleanup.

## Rotate the token

Set a new `TOOL_RUNTIME_TOKEN` in `.env` and recreate `tool-runtime`,
`backend` and `worker`. Nothing in the database changes.

## Footprint

These figures were measured on an earlier runtime image (linux/arm64, Docker
Desktop), before the runtime shared the application version:

| Condition                                      | Memory   |
| ---------------------------------------------- | -------- |
| Idle                                           | ~69 MiB  |
| 16 concurrent CPU-bound calls (default limit)  | ~580 MiB |
| After the burst                                | ~69 MiB  |

Each concurrent compute call costs about 32 MiB for its child process. A
tabular query child can use up to 256 MB for DuckDB plus 256 MB of spill
space. Such children and the Office renderers share
`TOOL_RUNTIME_TABULAR_CONCURRENCY` slots; PDF renders have their own pool of
two Python sidecars, and forecasts one sidecar at a time (`FORECAST_CONCURRENCY`).
A Timestral 28M forecast takes about a second and the container peaked at
850 MiB while the longest one (4,096 days of history, 180 days ahead) ran
next to a compute call, measured on linux/arm64 with the standard limits and
Landlock. The standard stack caps the container at 2 GiB, 2 CPUs
and 256 processes. `/tmp` is a 512 MiB tmpfs that holds job scratch space and
the 256 MiB cache, and it counts towards memory. If you raise a concurrency
setting, raise `mem_limit` with it.

## Failure behaviour

If the runtime is stopped or unreachable, the tool call fails and the
assistant answers without it. Chat is otherwise unaffected. Script errors,
timeouts and oversized results come back to the model as `ok: false` results,
so it can correct its code.
