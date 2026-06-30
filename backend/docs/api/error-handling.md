# API Error Handling

## Standard error shape

Most API errors return:

```json
{
  "message": "Human-readable reason",
  "eneo_error_code": 9001,
  "code": "forbidden_action",
  "context": {
    "auth_layer": "domain_policy",
    "resource_type": "assistant",
    "action": "publish"
  },
  "request_id": "req-123"
}
```

Fields:
- `message`: human-readable explanation.
- `eneo_error_code`: legacy numeric code used by existing SDKs.
- `code` (optional): stable string code for programmatic handling.
- `context` (optional): safe, non-sensitive metadata.
- `request_id` (optional): request correlation ID for support/debugging.

## Trace ID and error ID

Independent of the response body shape, every HTTP response (including 4xx and 5xx) carries the OpenTelemetry trace ID in the `X-Trace-Id` response header (32 hex chars). The legacy `X-Correlation-ID` header is emitted in parallel as a same-value alias during the migration period. Both headers are exposed via CORS.

For unhandled 500 errors, the response body additionally contains a short stable `error_id` (8 chars) that appears on the originating exception log line. `error_id` is the support-facing identifier safe to share with end users; `trace_id` is the operator-facing identifier used to correlate every log entry and span emitted during the request.

See [OBSERVABILITY.md](../../../docs/OBSERVABILITY.md) for the full ID contract, log schema, and trace flow.

## auth_layer values

- `identity`: API key is missing/invalid/expired/revoked (401).
- `guardrail`: denied by origin/IP/rate-limiting policy (403).
- `api_key_method`: key permission does not allow HTTP method (403).
- `api_key_resource`: key lacks required resource permission (403).
- `api_key_scope`: key scope does not match target resource (403).
- `domain_policy`: tenant/space role capability denied the action (403).

`auth_layer` is only emitted for 401/403 authorization denials.

## Debugging a 403 quickly

1. Check `code` first.
   - `insufficient_permission`: key permission level is too low for the method.
   - `insufficient_resource_permission`: missing resource permission.
   - `insufficient_scope`: scope mismatch.
   - `forbidden_action`: domain role/capability denied.
2. Check `context.auth_layer` to identify the stage that denied the request.
3. Use `request_id` for tracing logs and support escalation.
