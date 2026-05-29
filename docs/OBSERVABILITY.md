# Observability (OpenTelemetry)

**Status:** ✅ v1 (initial release)
**Audience:** Operators wiring log collection, backend & frontend developers, security reviewers

Eneo emits OpenTelemetry-shaped structured logs and distributed traces. The application is intentionally infrastructure-neutral: logs go to STDOUT as newline-delimited JSON (NDJSON) mapped to the [OTel Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/), and no spans or logs are exported via OTLP in v1. The choice of log collector, aggregation system, and visualization tool is left to the deployment.

---

## 1. What You Get

- **Structured logs** as NDJSON on STDOUT, one JSON object per line, with stable top-level fields (`timestamp`, `severity_text`, `severity_number`, `body`, `trace_id`, `span_id`, `trace_flags`, `resource`, `attributes`).
- **Distributed traces** with a real `TracerProvider`. A root span is created for every HTTP request (FastAPI auto-instrumentation), and child spans for SQLAlchemy queries, Redis operations, and outbound HTTP via `httpx` and `aiohttp`. ARQ background jobs create their own root traces.
- **W3C TraceContext propagation**. The `traceparent` header is honored on inbound requests and propagated on outbound backend-to-backend calls.
- **Support header to the frontend**: `X-Trace-Id` is set on every HTTP response, including 4xx and 5xx, and exposed via CORS. `X-Correlation-ID` is emitted in parallel as a legacy alias during the migration period.
- **Built-in redaction** of authorization headers, cookies, and sensitive query parameters (tokens, secrets, OAuth `code`/`state`) from both stdout logs and span attributes.

What v1 does not do is listed in §10.

---

## 2. Architecture Snapshot

```
                  ┌──────────────────────────────────────────────────────────┐
Frontend (SvelteKit)                                                          │
  reads X-Trace-Id from every response, includes it in error reports          │
                  │                                                           │
                  ▼                                                           │
            HTTP request                                                      │
                  │                                                           │
Backend (FastAPI) │                                                           │
  OTEL FastAPI middleware  ──►  creates server span (trace_id, span_id)       │
  TraceIdResponseMiddleware ──►  sets X-Trace-Id + X-Correlation-ID on        │
                                  http.response.start                         │
  RequestContextMiddleware  ──►  copies trace_id into contextvars             │
  OTELJSONFormatter         ──►  STDOUT NDJSON with trace_id/span_id          │
                  │                                                           │
                  ▼                                                           │
  Auto-instrumented child spans: SQLAlchemy, Redis, httpx, aiohttp            │
  Outbound HTTP: traceparent header is added (W3C propagation)                │
                  │                                                           │
                  ▼                                                           │
Worker (ARQ)                                                                  │
  init_observability() runs before lifespan.startup so engines/pools          │
  are patched. Each job creates its own root trace (v1 decision).             │
                  │                                                           │
                  ▼                                                           │
Container STDOUT  ─►  Log collector (Fluent Bit / Vector / Alloy / ...)       │
                  │   scrapes container logs, ships to chosen backend         │
                  ▼                                                           │
        Log aggregation system (infrastructure concern; see §9)               │
                  └──────────────────────────────────────────────────────────┘
```

Key files:
1. [backend/src/intric/main/observability.py](../backend/src/intric/main/observability.py) shared init for API and worker (`init_observability`, `instrument_fastapi`).
2. [backend/src/intric/main/logging.py](../backend/src/intric/main/logging.py) `OTELJSONFormatter` and severity mapping.
3. [backend/src/intric/server/middleware/trace_id.py](../backend/src/intric/server/middleware/trace_id.py) pure-ASGI middleware that injects `X-Trace-Id` on response start.
4. [backend/src/intric/server/middleware/request_context.py](../backend/src/intric/server/middleware/request_context.py) populates the per-request contextvars from the active span.

---

## 3. Configuration

All behavior is controlled via environment variables. No code change is required to enable, scope, or relabel telemetry.

| Variable | Default | Mapped to | Notes |
|---|---|---|---|
| `OTEL_SERVICE_NAME` | `eneo` | `resource.service.name` | Used as the log stream label in most aggregation systems. |
| `OTEL_SERVICE_VERSION` | `unknown` | `resource.service.version` | Set at build time (e.g. git SHA). Logs from an `unknown` version are not useful in incident triage. |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | `production` | `resource.deployment.environment.name` | OTel semantic conventions ≥ 1.24 use the `.name` suffix. Set to `development`, `staging`, etc. as appropriate. |
| `LOGLEVEL` | `INFO` | Python logging threshold | Existing variable, retained. |
| `JSON_LOGS` | `true` | Output format toggle | Set to `false` for human-readable output during local development. |

Variables are read once at process start. To pin `service.version` for a build:

```Dockerfile
ARG GIT_SHA
ENV OTEL_SERVICE_VERSION=${GIT_SHA}
```

Existing deployment templates ([docs/deployment/env_backend.template](deployment/env_backend.template)) document the OTel block alongside other backend settings.

---

## 4. Log Format

Each line emitted by the backend is a complete JSON object. Top-level fields are stable; everything else lives under `attributes` or `resource`.

```json
{
  "timestamp": "2026-01-15T10:30:45.123+00:00",
  "severity_text": "INFO",
  "severity_number": 9,
  "body": "Container: Initializing EncryptionService",
  "trace_id": "af2b2fe84425eb29776d4e7529fcccbc",
  "span_id": "c84e00cff7ba3d92",
  "trace_flags": "01",
  "attributes": {
    "correlation_id": "af2b2fe84425eb29776d4e7529fcccbc",
    "path": "/api/v1/spaces/type/organization/",
    "method": "GET",
    "status_code": 200,
    "tenant_slug": "exampletenant",
    "user_email": "user@example.com",
    "logger": "intric.main.container.container"
  },
  "resource": {
    "service.name": "eneo",
    "service.version": "1.2.3",
    "deployment.environment.name": "production"
  }
}
```

### Field guarantees

- `timestamp` is always present. Format is ISO 8601 with millisecond precision in UTC. (Not nanosecond `time_unix_nano`; this is a deliberate v1 deviation favoring human readability.)
- `severity_text` follows Python logging names: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. (Note: `WARN` and `FATAL` are accepted as input but normalize to `WARNING` and `CRITICAL` on output.)
- `severity_number` follows the [OTel severity_number mapping](https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber): `DEBUG=5`, `INFO=9`, `WARNING=13`, `ERROR=17`, `CRITICAL=21`.
- `body` is always a string in v1.
- `trace_id`, `span_id`, `trace_flags` are present only when a span is active during the log call. Background log lines (e.g. startup banners) have none.
- `resource.service.name`, `resource.service.version`, `resource.deployment.environment.name` are always present.
- `attributes.tenant_slug` is present for any log line emitted in a request scope where a tenant is resolved.

### Cardinality guidance for the aggregation system

Most log aggregation systems separate fields that are indexed for fast filtering from fields that are searched by parsing the line at query time. Configure your aggregator according to cardinality:

| Cardinality | Examples | Recommendation |
|---|---|---|
| Low | `resource.service.name`, `resource.deployment.environment.name`, `severity_text` | Index. Use for filtering to the right log stream. |
| Medium | `attributes.path`, `attributes.method`, `attributes.status_code` | Optional index depending on aggregator capacity. |
| High | `trace_id`, `attributes.tenant_slug`, `attributes.user_email`, `attributes.correlation_id` | Do not pre-index. Search via JSON parsing at query time. |

How this is configured is an infrastructure concern, but the NDJSON format is designed to make the mapping natural: the `resource` block is low-cardinality metadata; `attributes` carries the high-cardinality, request-specific data.

---

## 5. ID Contract

Eneo uses three distinct IDs. They are not interchangeable.

| ID | Where it lives | Purpose |
|---|---|---|
| `trace_id` | Top-level log field, `X-Trace-Id` response header, OTel span context | Primary correlation ID. Links every log line and span produced by a single request. |
| `error_id` | Response body for unhandled exceptions, log attribute on the corresponding error line | Stable 8-char identifier given to end users so support can locate the failure. |
| `correlation_id` | Top-level log field (aliased to `trace_id`), `X-Correlation-ID` response header | Legacy alias for `trace_id` kept during the migration period. |

### Migration path for `correlation_id`

`correlation_id` predates the OTel work. It is retained because existing support flows, dashboards, and the frontend client read `X-Correlation-ID`. During the migration period:

- The backend sets `correlation_id = trace_id` in contextvars, in log lines, and in the `X-Correlation-ID` response header. The two fields always carry the same value.
- The frontend's `IntricError.getTraceId()` reads `X-Trace-Id` first and falls back to `X-Correlation-ID`, so both old and new backends are handled.
- New code should reference `trace_id` / `X-Trace-Id` only.

Removal of `correlation_id` and `X-Correlation-ID` is deferred until support flows, internal dashboards, and frontend consumers have migrated. There is no specific deprecation date in v1; the alias is free to retire when no active reader remains.

### `error_id`

Unhandled exceptions produce a response body of the form:

```json
{
  "error_id": "a1b2c3d4",
  "message": "An unexpected error occurred. Please try again or contact support with the error_id."
}
```

The same `error_id` appears in the log line for the originating exception. `error_id` is short (8 chars) and stable across the response and the logs so it can be quoted by an end user. Unlike `trace_id`, it does not exist on successful responses.

---

## 6. Trace Flow

### Inbound requests

The OTel FastAPI instrumentation creates a server span for each request. If the incoming request carries a `traceparent` header (W3C TraceContext), the new span continues that trace; otherwise a new trace is started.

`TraceIdResponseMiddleware` sets `X-Trace-Id` (and `X-Correlation-ID`) on `http.response.start`, which guarantees the headers are present on every status code including 4xx and 5xx. The middleware is pure-ASGI rather than `BaseHTTPMiddleware`, which would create a context-copy boundary that loses the active server span.

CORS exposes both headers via `Access-Control-Expose-Headers`. The list of exposed trace headers is defined once in [backend/src/intric/server/main.py](../backend/src/intric/server/main.py) as `_TRACE_EXPOSE_HEADERS` and reused in the normal CORS configuration and in the manual CORS blocks used by 500-error responses.

### Outbound backend-to-backend calls

`httpx` and `aiohttp` are auto-instrumented. Any call made through them inherits the active span as parent and adds a `traceparent` header to the outbound request. The receiving backend (Eneo or otherwise, if it supports W3C TraceContext) continues the same trace.

### Log correlation

Every log call inside an active span receives the span's `trace_id` and `span_id` as top-level fields. Background log lines (logs emitted at module import, in idle workers, etc.) carry no IDs because no span is active. To correlate all log entries from one HTTP call, filter by `trace_id`.

### ARQ background jobs (v1)

ARQ has no built-in metadata envelope separate from job kwargs, so injecting `traceparent` into job arguments would mix trace context with domain parameters. v1 decision: each ARQ job creates its own root trace. Consequence: there is no end-to-end waterfall from an HTTP request to the ARQ job it enqueues. All log entries within a job correlate via the job's own `trace_id`. Request-to-job propagation is planned for a future version once a clean metadata mechanism is available.

---

## 7. Frontend Integration

The frontend treats `X-Trace-Id` as a support header, not a distributed-tracing carrier. There is no browser OTel SDK and no span export from the browser in v1.

### What the frontend does

- `IntricError.getTraceId()` (in [`@intric/intric-js`](../frontend/packages/intric-js/src/client/client.js)) reads `X-Trace-Id` from the response headers, falling back to `X-Correlation-ID` if absent. Every error from an Eneo API call carries the trace ID without further plumbing.
- SvelteKit error hooks ([hooks.client.ts](../frontend/apps/web/src/hooks.client.ts), [hooks.server.ts](../frontend/apps/web/src/hooks.server.ts)) include `traceId` on the error payload, so `$page.error.traceId` is available to display.
- Auth flows ([intric.server.ts](../frontend/apps/web/src/lib/features/auth/intric.server.ts), [oidc.server.ts](../frontend/apps/web/src/lib/features/auth/oidc.server.ts)) read the trace ID from response headers and pass it through `LoginError.traceId` so callback pages can surface it to the user and log it.

### What the frontend does not do

- It does not generate, propagate, or send `traceparent` itself. `traceparent` is a backend-to-backend W3C contract.
- It does not export spans or logs to any backend in v1.

Surfacing the trace ID to users (in error toasts, support links, etc.) is a UI concern; the value is always available on `IntricError.getTraceId()` and `App.Error.traceId`.

---

## 8. Redaction Policy

Redaction is enforced at two layers: stdout log attributes and auto-instrumented span attributes. Coverage is verified in tests for both layers.

### Headers that are never logged

- `Authorization`
- `Cookie`
- `Set-Cookie`

### Query parameters that are replaced with `[REDACTED]`

The full list is defined as a regular expression in [observability.py](../backend/src/intric/main/observability.py) (`_SENSITIVE_PARAM_RE`):

- Exact matches: `code`, `state`, `token`, `access_token`, `refresh_token`, `client_secret`
- Wildcard matches: any parameter whose name contains `token` or `secret` (case-insensitive)

The same redaction applies to both:
1. URL strings carried in log attributes (via `redact_url_query()`).
2. URL attributes set by auto-instrumented spans: `url.full`, `http.url`, `http.target` (via `server_request_hook` on FastAPI server spans and `request_hook` on outbound httpx / aiohttp client spans).

### Request and response bodies

Not logged by default. Adding body logging requires a deliberate code change and a redaction review.

### `user_email`

Included in log attributes as a deliberate decision; existing audit behavior is preserved. It is high-cardinality PII and the infrastructure is recommended not to pre-index it (see §4).

### Verifying redaction in your environment

The test suite parameterizes redaction across all sensitive parameter names for both the log path and the span attribute path. To re-run locally:

```bash
cd backend
uv run pytest tests/unittests/observability/ -v
```

---

## 9. Reference Setup: Kubernetes Log Collection

The application emits NDJSON to STDOUT; the rest is your infrastructure's job. Two minimal reference configurations follow. Both assume your aggregation system has a JSON parser available downstream.

### Fluent Bit (DaemonSet, tailing container logs)

`fluent-bit.conf`:

```ini
[SERVICE]
    Flush         1
    Daemon        Off
    Log_Level     warn
    Parsers_File  parsers.conf

[INPUT]
    Name              tail
    Tag               eneo.*
    Path              /var/log/containers/*eneo*.log
    Parser            cri
    Refresh_Interval  5
    Skip_Long_Lines   On

[FILTER]
    Name              parser
    Match             eneo.*
    Key_Name          log
    Parser            json
    Reserve_Data      On

[OUTPUT]
    Name              loki
    Match             eneo.*
    Host              loki.observability.svc.cluster.local
    Port              3100
    Labels            service=$resource['service.name'], env=$resource['deployment.environment.name'], severity=$severity_text
    Line_Format       json
```

`parsers.conf` already ships a `json` parser; ensure it's available in your image.

### Vector (DaemonSet, kubernetes_logs source)

`vector.yaml`:

```yaml
sources:
  eneo_logs:
    type: kubernetes_logs
    extra_label_selector: "app.kubernetes.io/name=eneo"

transforms:
  parse_eneo:
    type: remap
    inputs: [eneo_logs]
    source: |
      parsed, err = parse_json(.message)
      if err == null { . = merge(., parsed) }

sinks:
  loki:
    type: loki
    inputs: [parse_eneo]
    endpoint: http://loki.observability.svc.cluster.local:3100
    labels:
      service: '{{ resource."service.name" }}'
      env: '{{ resource."deployment.environment.name" }}'
      severity: '{{ severity_text }}'
    encoding:
      codec: json
```

### Querying by trace ID

Once logs land in your aggregation system, the primary correlation pattern is:

```
{service="eneo"} | json | trace_id = "af2b2fe84425eb29776d4e7529fcccbc"
```

Any log entry from one HTTP request shares the same `trace_id`. The end user's `error_id` (8 chars) appears as `attributes.error_id` on the originating exception log line and in the response body, which gives support a stable handle that does not require sharing a full trace ID with end users.

---

## 10. v1 Exclusions

The following are explicitly **not** part of v1:

- **No span or log export via OTLP.** The `TracerProvider` has no production exporters. No external collector endpoint is required for the application to start or function.
- **No trace backend.** Visual trace waterfalls require active span export and are deferred to v2.
- **No frontend OTel SDK.** The browser does not generate, export, or propagate spans.
- **No WebSocket or SSE tracing.** SSE requests can produce extremely long-lived spans without special handling and need a dedicated solution.
- **No request-to-ARQ-job trace propagation.** See §6.
- **No metrics export** (Prometheus, OTLP metrics).
- **No Sentry initialization.** The Sentry SDK remains a declared dependency but is not initialized.
- **No custom spans** beyond what auto-instrumentation provides.
- **No vendor-specific log management integration** beyond what the OTel format and stdout enable.

---

## 11. Related Documents

- [Architecture Guide](./ARCHITECTURE.md) end-to-end system overview.
- [Deployment Guide](./DEPLOYMENT.md) production deployment, env templates.
- [Security](./SECURITY.md) redaction policy in the broader security context.
- [Troubleshooting](./TROUBLESHOOTING.md) operational issues, including how to use `trace_id` and `error_id` for support.
- [API Error Handling](../backend/docs/api/error-handling.md) error response shape (`error_id`, `intric_error_code`, `request_id`).
