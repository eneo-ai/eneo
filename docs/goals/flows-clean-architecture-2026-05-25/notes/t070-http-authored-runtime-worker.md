# T070 Worker: Authored HTTP Runtime Execution

## Pre-Implementation Commitments

T070 implements authored HTTP runtime execution by reusing existing owners:

- `HttpAuthoredConfig` owns the authored JSON shape.
- `decrypt_authored_config` owns authored secret decryption.
- `compile_http_config` owns authored request compilation.
- `runtime/http_orchestration.py` owns runtime send/audit orchestration.
- `flow_run_rerun_graph.py` owns rerun dependency extraction.

No public API, OpenAPI, generated-client, schema, migration, retention, service-key identity, review/rerun product-policy, materialized webhook request storage, or Flow AI Builder files are in scope.

Legacy flat `headers/body_template/body_json` support remains in place. Deleting or migrating it requires persisted draft and immutable published-snapshot preflight.

## Test Commitments

The authored runtime tests must use request-fingerprint assertions. Each relevant test captures `send_http_request.await_args.kwargs` and asserts exact values for:

- resolved `url`;
- `headers["Authorization"]` for bearer auth;
- API-key/basic/custom headers where present;
- `json_body` or `body_bytes`;
- `timeout_seconds`;
- webhook `Idempotency-Key` after authored compilation.

Required red tests:

- authored HTTP input compiles bearer auth, custom header, JSON body template, URL interpolation, and timeout into the outbound request;
- authored webhook compiles custom header/body and still adds the idempotency key;
- authored webhook with `body.mode == "auto"` falls back to `text_payload.encode("utf-8")`;
- authored timeout exceeding the runtime cap raises `TypedIOValidationException(code="typed_io_http_invalid_config")`;
- `compile_http_config(..., variables={}, interpolate=fn)` still invokes the interpolation function;
- authored bearer-token templating reaches the wire as the Authorization header;
- rerun graph detects authored URL/header/body/auth templates with existing dependency kinds;
- rerun graph does not fabricate dependencies for authored body mode `none` with no templates.

## Rerun Dependency Mapping

T070 must not add new `RerunDependencyKind` values. Authored HTTP config maps to existing dependency kinds:

- authored `url` -> `INPUT_CONFIG_URL` / `OUTPUT_CONFIG_URL`;
- authored `custom_headers` and `auth` fields -> `INPUT_CONFIG_HEADERS` / `OUTPUT_CONFIG_HEADERS`;
- authored `body.template` -> `INPUT_CONFIG_BODY_TEMPLATE` / `OUTPUT_CONFIG_BODY_TEMPLATE`.

This means a `*_CONFIG_HEADERS` invalidation can come from legacy flat `headers`, authored `custom_headers`, or authored `auth` fields.

Implementation shape: split authored and legacy rerun extraction into narrowly named private functions under `flow_run_rerun_graph.py`, with a thin dispatcher choosing the branch. Do not add a generic helper or new module.

## Auth Templating Policy

Auth-field templating remains allowed because the existing authored compiler already interpolates bearer token, API-key header name/key, and basic username/password, and legacy flat headers already allow variables to produce Authorization/API-key header values. T070 makes runtime reuse the existing backend authored compiler; it does not introduce a new API syntax.

## Typed Boundary

Do not widen the runtime seam. New authored handling should flow:

`dict input_config/output_config` -> `HttpAuthoredConfig` -> `decrypt_authored_config` -> `compile_http_config` -> `EffectiveHttpRequest` -> `send_http_request`.

No new `dict[str, Any]`, `cast(Any)`, `type: ignore`, or `pyright: ignore` lines should be added.

## Follow-Up Trigger

Named follow-up after T070:

- Collapse `FlowHttpOrchestrationDeps` in `backend/src/intric/flows/runtime/http_orchestration.py` from flat-specific `build_headers` / `resolve_request_body` / `resolve_timeout_seconds` callbacks toward a single effective-request boundary once persisted draft and published-snapshot preflight determines whether legacy flat config can be deleted or must remain as an explicit typed compatibility path.
- Review `compile_http_config` handling of non-string `CustomHeader.value` after secret-sentinel preflight. It currently compiles non-string values to an empty header value; T070 records this inherited compiler behavior without widening the runtime slice.
- Widen `is_authored_config` to accept a read-only mapping once the normalizer owner is in scope; T070 currently copies the rerun-graph mapping before calling the existing owner to avoid broadening `http_transport/normalizer.py`.
- Consider comparing authored rerun extraction against `HttpAuthMode` / `HttpBodyMode` enum values when the extractor owner is next touched. T070 keeps the public wire strings local to avoid a wider transport import change.

This is not part of T070 because the current slice must first make authored runtime behavior correct while preserving legacy compatibility.

Audit-log redaction for runtime-interpolated authored secrets is out of scope for T070; this slice only routes execution through the existing authored compiler and preserves current audit payload behavior.

## Worktree Hygiene

T070 staging must use explicit `git add` only for T070 allowed files. Unrelated modified and untracked files remain in the worktree and must not be staged or committed.
