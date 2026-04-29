# Flow API Maintainer Playbook

This playbook is the Batch 1 API source-of-truth handoff for Flow and Flow AI
Builder. It turns PRD-004 into repeatable maintainer steps.

## Source-Of-Truth Rules

| Surface | Canonical owner | Do not move ownership to |
|---|---|---|
| Route path, method, operation ID, tags, request model, response model, status codes | The owning Flow router under `backend/src/intric/flows/api/` | `backend/src/intric/server/main.py` OpenAPI postprocessing |
| Shared pagination contracts | `backend/src/intric/main/models.py` | Per-router duplicate page schemas |
| Flow request/response body models | `backend/src/intric/flows/api/flow_models.py` | Frontend manual types or generated-client patches |
| Error examples and `GeneralError` response shape | `backend/src/intric/flows/api/flow_api_common.py` | Inline copied OpenAPI dictionaries |
| Runtime create/poll/list/evidence behavior | Flow application services plus thin HTTP routers | Frontend wrapper assumptions |
| Hand-written JS convenience methods | `frontend/packages/intric-js/src/endpoints/flows.js` | Generated schema files |

## Adding Or Changing A Flow Endpoint

1. Identify the router that owns the use case. Create no new router unless the route
   belongs to a new durable API surface.
2. Define the request and response models in `flow_models.py` unless the model is a
   reusable cross-domain contract.
3. Add an explicit `operation_id`, summary, description, status code, response model,
   and typed error responses with `error_response`.
4. Keep the router thin: parse HTTP input, enforce access, call the application
   service, and translate the response.
5. Add or update `backend/tests/unit/test_flow_openapi_contract.py` before changing
   generated-client-sensitive behavior.
6. Add integration coverage when the route changes runtime behavior, permissions,
   idempotency, pagination, evidence, or file upload semantics.
7. Update `frontend/packages/intric-js/src/endpoints/flows.js` only for hand-written
   convenience methods or request-shaping logic that cannot come from generated types.

## Public-Contract Changes

Treat these as public-contract changes:

- route path or method
- operation ID
- tag group
- request model or response model
- required field, enum value, content type, header, or status code
- pagination shape
- machine-readable error code or `GeneralError` schema
- generated OpenAPI component name used by `frontend/packages/intric-js/src/types/schema.d.ts`

When any of those change, document the generated-client impact in the batch journal
and update the targeted `intric-js` tests. Generated-client/package naming remains
owned by Batch 5.

## Pagination

Use `OffsetPaginatedResponse[T]` for offset/limit endpoints that need `has_more`.
Do not add `has_more` to `PaginatedResponse` until a broader pagination migration is
planned; doing so would change unrelated endpoints. Flow list routes should fetch
`limit + 1`, return only `limit` items, and set `has_more` from the over-fetch result.

## Evidence Export

Evidence export is a JSON attachment. The route must document both:

- `application/json` schema: `FlowRunEvidenceExportResponse`
- `Content-Disposition` attachment header

Validate the export payload with `FlowRunEvidenceExportResponse` before returning the
attachment. Do not rely on a decorator-level `response_model` when returning a raw
`Response`.

## Idempotency

`Idempotency-Key` replay is tied to the retained `flow_runs` row. Reusing the same key
with the same normalized request returns the existing run. Reusing the same key with
a different normalized request returns `flow_run_idempotency_conflict`.

Do not add TTL columns or retention migrations in API cleanup work. If a later runtime
or retention batch changes run deletion semantics, it must treat idempotency replay as
a public-contract impact and update the docs/tests in the same change.

## Validation

For Flow API source-of-truth changes, run at minimum:

```bash
cd backend && uv run pytest \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/main/models.py \
  src/intric/server/main.py \
  src/intric/flows/api/flow_upload_router.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_authoring_router.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/api/flow_models.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py
```

```bash
cd frontend && ./node_modules/.bin/vitest run packages/intric-js/src/endpoints/flows.test.js
```
