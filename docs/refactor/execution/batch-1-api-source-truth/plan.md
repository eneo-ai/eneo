# Batch 1 — API Source Truth Plan

## Scope

Implement PRD-004 API source truth for Flow / Flow AI Builder API consumer and maintainer DX.

Batch 1 starts from these committed checkpoints:

- Batch 0 source/test checkpoint: `d6a9365e477b83651d94566f58a9a7e13d0b9363`
- Post-Batch-0 governance/docs checkpoints:
  - `88cfc4016aa4c5b69506bee5f8b887a1f70a47c1`
  - `8f21fd4f9ca745df8bd0761923350e2f304640ed`
  - `ad472c61bf34b3a5ced13198e141c78c693e5bc0`

Batch 1 is not a generated-client/package rename batch. `frontend/packages/intric-js` remains `@intric/intric-js`; generated-client/package naming is deferred to Batch 5 unless PRD-004 directly requires a narrow wrapper fix. The Python backend namespace remains `intric.*`; do not create `eneo.*` alias modules.

## Current API / OpenAPI Source-Of-Truth Owners

| Surface | Current source owner | Current false owner / drift | Batch 1 direction |
|---|---|---|---|
| Flow file upload | `backend/src/intric/flows/api/flow_upload_router.py` owns `/flows/{id}/files/` and `/flows/{id}/steps/{step_id}/runtime-files/` endpoint signatures, multipart field name, status code, error examples, and policy docs. | `backend/src/intric/server/main.py` has a Flow-specific OpenAPI component rewrite for `/api/v1/flows/{id}/files/`, which makes `server/main.py` a false owner for Flow upload schema. | Add/keep route-level OpenAPI pins, then remove the Flow-specific upload schema rewrite from `server/main.py` only after the route-level schema remains correct. |
| Evidence view/export | `backend/src/intric/flows/api/flow_run_evidence_router.py` owns routes, query params, permission docs, audit-deny responses, and export behavior. `backend/src/intric/flows/api/flow_models.py` owns `FlowRunEvidenceResponse` and `FlowRunEvidenceExportResponse`. | Export currently returns a raw `Response` JSON attachment while declaring a response model. The JSON body is right, but OpenAPI should explicitly document the attachment header and JSON schema from the route owner. | Keep the existing JSON attachment behavior in this iteration and make the OpenAPI 200 response accurately describe `application/json` plus `Content-Disposition`. Switching to a non-attachment JSON endpoint would be a public behavior change and is not necessary for PRD-004. |
| Flow list pagination | `backend/src/intric/flows/api/flow_authoring_router.py` owns list route behavior for `/flows/`. `backend/src/intric/main/models.py` owns reusable page response contracts. | `PaginatedResponse` only exposes page `count`; adding optional `has_more` to it would serialize `has_more: null` for unrelated endpoints and broaden the public behavior change. | Add a reusable `OffsetPaginatedResponse[T]` response contract in `main.models`, use it only for Flow list routes in Batch 1, over-fetch `limit + 1`, and return required `has_more`. |
| Flow run list pagination | `backend/src/intric/flows/api/flow_run_execution_router.py` owns `/flows/{id}/runs/` list route behavior. `backend/src/intric/main/models.py` owns reusable page response contracts. | Same global `PaginatedResponse` limitation as above. | Use the same `OffsetPaginatedResponse[FlowRunPublic]`, over-fetch `limit + 1`, and keep repository/service count behavior unchanged unless needed. |
| Start run | `backend/src/intric/flows/api/flow_run_execution_router.py` owns HTTP path/header/body translation. `backend/src/intric/flows/api/flow_models.py` owns `FlowRunCreateRequest`. `backend/src/intric/flows/application/flow_run_service.py` owns published-version validation, normalized input snapshot, idempotency fingerprint, conflict behavior, and creation orchestration. | The JS wrapper currently derives idempotency from a run intent that contains path-owned `flow_id`, then deletes `flow_id` before sending the request body. The OpenAPI request body remains backend-owned. | Split client intent normalization from request-body construction; do not change backend top-level `file_ids` yet. Add API and JS pins for idempotency behavior and request body shape. |
| Poll/result | `backend/src/intric/flows/api/flow_run_execution_router.py` owns `GET /flows/{id}/runs/{run_id}/`. `backend/src/intric/flows/api/flow_run_steps_router.py` owns step output listing. `FlowRunPublic` / `FlowRunStepPublic` in `flow_models.py` own generated-client-sensitive response schema. | Poll/result behavior exists but lacks one external-consumer integration contract that starts from public routes. | Add `test_flow_consumer_api_contract.py` for start-run, idempotent replay/conflict, poll/result, and step output route behavior. |
| Generated-client-sensitive schema | Backend OpenAPI route/schema owners are the source of truth. `frontend/packages/intric-js/src/types/schema.d.ts` is generated output, and `frontend/packages/intric-js/src/endpoints/flows.js` is a hand-written wrapper over those paths. | `frontend/packages/intric-js/src/types/resources.d.ts` contains manual Flow resource aliases; full generated-type migration belongs to Batch 5. | Batch 1 may update the wrapper and wrapper tests for PRD-004 methods and request shape. Do not rename package, do not make manual Flow type migration broad, and only regenerate schema if backend OpenAPI changes require it. |

## Behavior Pins To Add Or Rewrite BEFORE Deletion / Contract Changes

- [x] Extend `backend/tests/unit/test_flow_openapi_contract.py` before removing the Flow-specific upload patch from `server/main.py`:
  - upload and runtime-file upload request bodies expose `upload_file` as required binary multipart fields
  - `server/main.py` is no longer needed as a Flow upload schema owner after route-level schema still passes
  - evidence export 200 response documents `application/json`, `FlowRunEvidenceExportResponse`, and `Content-Disposition`
  - rewrite the existing pagination schema pin before changing pagination behavior; Flow list and run list response schemas expose required `has_more`
  - pin the observed OpenAPI component names for `OffsetPaginatedResponse[FlowSparsePublic]` and `OffsetPaginatedResponse[FlowRunPublic]` after app schema generation confirms them
  - create-run request schema keeps `step_inputs` and still documents top-level `file_ids` as a surviving compatibility surface
  - operation IDs and route paths stay stable unless a deliberate public-contract change is documented
- [x] Add `backend/tests/integration/flows/test_flow_consumer_api_contract.py`:
  - published runtime discovery / run contract route is reachable through the public API
  - create run accepts `step_inputs` and optional top-level `file_ids` during the Batch 1 compatibility window
  - same idempotency key + same payload replays the existing run
  - same idempotency key + different payload returns `flow_run_idempotency_conflict`
  - poll/result route returns `FlowRunPublic` fields and step output route returns consumer-visible step output
  - list pagination returns `has_more` for over-full pages
  - reuse the existing evidence-contract seed shape by extracting a narrow shared fixture helper if direct public-route seeding is too broad for this batch
- [x] Verify `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`:
  - existing JSON attachment behavior remains explicit
  - content type, disposition header, schema version, redaction fields, and historical evidence keys are pinned as public/persisted compatibility surfaces
- [x] Document/test current idempotency retention semantics without adding a TTL migration in this batch:
  - idempotency replay lasts as long as the matching retained `flow_runs` row exists
  - a later retention/deletion policy may remove the replay source; clients must treat run id polling as the durable follow-up handle
  - adding explicit idempotency TTL columns or data migrations belongs to the later data-model/runtime batches
- [x] Extend `frontend/packages/intric-js/src/endpoints/flows.test.js` before editing the wrapper:
  - `flows.published.get({ id })` calls `GET /api/v1/flows/{id}/published/`
  - `flows.runs.create` sends a request body without path-owned `flow_id`
  - idempotency-key derivation still includes the flow id in the fingerprint input
  - wrapper tests keep top-level `file_ids` only as the documented Batch 4 compatibility surface

If the new HTTP consumer contract hits a fixture gap, document the exact blocked fixture in the journal and keep the OpenAPI/client behavior pins. Do not delete or weaken existing router tests to compensate.

## Files To Change

### Tier A — Source-Only / Local API Ownership

Expected source changes:

- `backend/src/intric/main/models.py`
  - add reusable `OffsetPaginatedResponse[T]` with required `has_more`
  - do not mutate `PaginatedResponse`; unrelated endpoints must not start serializing `has_more: null`
- `backend/src/intric/server/main.py`
  - remove only the Flow-specific upload OpenAPI rewrite after route-level pins pass
  - keep global WSO2, `NOT_PROVIDED`, AI Builder tag, and SSE OpenAPI fixes
  - retain `_retag_flow_ai_builder_operations` in this batch because parent router tag inheritance currently makes AI Builder tag presentation a routing-composition concern, not an upload/evidence source-truth owner
- `backend/src/intric/flows/api/flow_upload_router.py`
  - keep multipart schema ownership in route-level endpoint metadata/signatures
- `backend/src/intric/flows/api/flow_run_evidence_router.py`
  - make evidence export OpenAPI response accurate for JSON attachment behavior
- `backend/src/intric/flows/api/flow_authoring_router.py`
  - return Flow-specific offset page with `has_more`
- `backend/src/intric/flows/api/flow_run_execution_router.py`
  - return Flow-specific run page with `has_more`
  - update idempotency/pagination descriptions if needed
- `backend/src/intric/flows/api/flow_models.py`
  - keep evidence and run request/response schemas as the generated-client-sensitive Flow model owner
  - do not add Flow-local pagination schemas; if the shared reusable `OffsetPaginatedResponse` proves unsafe during implementation, stop and record the evidence instead of silently branching the design
- `frontend/packages/intric-js/src/endpoints/flows.js`
  - add published runtime wrapper method
  - split idempotency intent normalization from request body construction so no `delete flow_id` pattern remains

Expected test/doc changes:

- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/integration/flows/flow_api_contract_fixtures.py` if the consumer/evidence contract tests need shared seeding without importing from another test module
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `backend/tests/unittests/flows/test_flow_router.py` only for narrow pagination return-shape fallout; do not broaden mock-heavy router coverage
- `frontend/packages/intric-js/src/endpoints/flows.test.js`
- `docs/refactor/api-maintainer-playbook.md`
- `docs/refactor/execution/batch-1-api-source-truth/plan.md`
- `docs/refactor/execution/batch-1-api-source-truth/journal.md`
- later in the loop: `retrospective-1.md` and `claude-reconciliation-1.md`

### Tier B — Persisted / Public Surfaces Not To Delete In Batch 1

| Surface | Owner | Why not deleted in Batch 1 | Later owner |
|---|---|---|---|
| Top-level run request `file_ids` | `FlowRunCreateRequest`, `FlowRunService.create_run`, `flow_run_step_inputs`, `frontend/packages/intric-js/src/endpoints/flows.js` | Public request shape and persisted run input snapshot. PRD-004 pins it and documents generated-client impact; removal is tied to per-step file mapping and idempotency updates. | Batch 4 / PRD-003 with backend + `intric-js` + generated type coordination. |
| `template_file_id` in template outputs | Flow template asset compatibility code and historical published definitions | Historical definitions/readers may still contain this key. | Batch 4 or later compatibility cleanup after persisted-reader proof. |
| Old form field type values | Flow metadata/form-schema readers and run-contract rendering | Persisted metadata and external form schemas can still contain old values. | Batch 4/10 after schema-version and migration decision. |
| HTTP config converters / authored config readers | Flow HTTP authored config conversion code | Persisted Flow steps may contain authored configs; not part of API source-truth cleanup. | Dedicated HTTP config migration/backlog item. |
| Historical evidence/export keys | `flow_run_export_json`, `FlowRunEvidenceExportResponse`, existing evidence tests | Evidence export is audit/support history. New docs should not advertise obsolete internals, but readers/export compatibility remains. | Evidence schema-version migration, not Batch 1. |
| Existing `_alias` operation IDs | Flow run/evidence leaf routers and generated clients | Operation IDs are generated-client-sensitive public contracts. Renaming is a public-contract change. | Consider in a separate API stabilization pass if explicitly approved. |
| `OffsetPaginatedResponse` as a fifth pagination type | `backend/src/intric/main/models.py` | Batch 1 uses it as an opt-in public contract to avoid changing unrelated `PaginatedResponse` runtime output. | Consolidate when a second module adopts `has_more`; then consider hoisting the field into the canonical pagination contract and deleting the temporary offset-specific type. |
| `_retag_flow_ai_builder_operations` | `backend/src/intric/server/main.py` | Parent `/flows` router tag inheritance makes route-local AI Builder tags insufficient today, and deleting the helper would mix AI Builder operations into the Flow tag group. | Delete when AI Builder routing moves to a stable tags-on-include composition or a dedicated API tag policy replaces this postprocessor. |

No source-only shim should be restored as compatibility unless a real external consumer is proven.

## Public Contract / Generated Client Impact

- Adding `has_more` to Flow list and run-list responses is an additive public response-schema change and affects generated clients.
- The expected generated-client-sensitive schema names should move from `PaginatedResponse_FlowSparsePublic_` / `PaginatedResponse_FlowRunPublic_` to the observed `OffsetPaginatedResponse[...]` component names. The implementation must verify the exact generated names from the app OpenAPI before writing the final pin. Batch 1 should update generated schema only if the backend OpenAPI diff requires it; package naming remains deferred to Batch 5.
- Changing route paths, operation IDs, request models, response models, pagination shape, error shape, content type, or attachment headers is a public-contract change.
- Removing `server/main.py`'s Flow upload OpenAPI rewrite should be generated-client-neutral if route-owned schema remains identical.
- Evidence export will remain `application/json` with an attachment header in this iteration; documenting the header is an OpenAPI contract correction, not a runtime behavior change.
- Evidence export should remove the misleading decorator-level `response_model` and instead declare the 200 JSON attachment schema and `Content-Disposition` header in route-owned `responses`, while validating the payload with `FlowRunEvidenceExportResponse` before serializing it.
- The JS wrapper change for published runtime is additive.
- The JS wrapper change that removes `delete normalizedRequest.flow_id` is an internal wrapper cleanup that preserves the transmitted request body; it should reduce generated-client mismatch without changing API behavior.
- Generated-client/package naming is deferred to Batch 5. Do not rename `@intric/intric-js`, `frontend/packages/intric-js`, Python imports, OpenAPI tags, audit categories, or telemetry prefixes in this batch.
- Frontend app callers currently use the wrapper list results' `items` shape rather than the generated component names directly. Batch 1 still treats backend pagination schema changes as generated-client-sensitive and will validate the targeted wrapper tests.

## Claude Plan Review Reconciliation

Claude iteration 1 returned `GREEN_LIGHT: no`. The following plan changes reconcile the accepted findings before implementation:

- Accepted: rewrite the existing pagination OpenAPI pin before changing route response models.
- Accepted with modification: avoid Flow-local pagination schemas, but also avoid mutating `PaginatedResponse`; use a reusable `OffsetPaginatedResponse` for Flow routes only.
- Accepted: evidence export must have an explicit route-owned OpenAPI mechanism. The planned mechanism is `responses={200: ...}` plus payload validation before returning the JSON attachment.
- Accepted: audit generated-client-sensitive frontend callers before deciding whether schema generation is required; keep package naming deferred to Batch 5.
- Accepted: document/test row-retention-based idempotency replay semantics without introducing a TTL migration in Batch 1.
- Accepted: keep error examples on the existing Flow API helper path and do not broaden AI Builder error-helper cleanup into this batch.
- Accepted with scope note: keep `_retag_flow_ai_builder_operations` for now; tag policy/routing composition belongs to a later branding/API cleanup.
- Accepted: do not import test helpers from another test module; extract a narrow shared fixture helper only if the new consumer contract needs the existing seed setup.
- Deferred: renaming `_alias` operation IDs is a generated-client-sensitive public-contract change and is not part of Batch 1.

## Validation Commands

Implementation order row for Batch 1 says:

```text
Backend OpenAPI tests; targeted `frontend/packages/intric-js` tests after env fix
```

Operationalized commands for this iteration:

```bash
git diff --check -- \
  backend/src/intric/main/models.py \
  backend/src/intric/server/main.py \
  backend/src/intric/flows/api \
  backend/tests/unit/test_flow_openapi_contract.py \
  backend/tests/integration/flows/flow_api_contract_fixtures.py \
  backend/tests/integration/flows/test_flow_consumer_api_contract.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unittests/flows/test_flow_router.py \
  frontend/packages/intric-js/src/endpoints/flows.js \
  frontend/packages/intric-js/src/endpoints/flows.test.js \
  frontend/packages/intric-js/src/types/schema.d.ts \
  docs/refactor/api-maintainer-playbook.md \
  docs/refactor/execution/batch-1-api-source-truth
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  -q
```

```bash
cd backend && uv run pytest \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  -q
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright \
  src/intric/main/models.py \
  src/intric/server/main.py \
  src/intric/flows/api/flow_upload_router.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_authoring_router.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/api/flow_models.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unittests/flows/test_flow_router.py
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
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unittests/flows/test_flow_router.py
```

```bash
cd frontend && ./node_modules/.bin/vitest run packages/intric-js/src/endpoints/flows.test.js
```

```bash
rg -n "flow_upload_operation|/api/v1/flows/\\{id\\}/files/|Body_upload_flow_file" \
  backend/src/intric/server/main.py
```

Expected after implementation: no Flow-specific upload schema rewrite remains in `server/main.py`. If Docker execution is blocked by the host approval policy, classify it as an environment issue and run the local fallback commands.

## Acceptance Criteria (Verbatim From PRD-004)

- [x] Flow-specific OpenAPI postprocessing removed or reduced to zero for upload/evidence.
- [x] Evidence export declared response matches actual response.
- [x] Pagination response has `has_more` or `total_count`.
- [x] `flows.published` exists in JS wrapper.
- [x] Idempotency retention documented/tested.
- [x] Error examples use one canonical helper.
- [x] API maintainer playbook exists.

## Out Of Scope For This Batch

- Do not start Batch 2.
- Do not remove top-level run request `file_ids`.
- Do not implement step rerun, pause/review/resume, or human-review endpoints.
- Do not migrate frontend workflow state ownership.
- Do not migrate `frontend/packages/intric-js` package naming; Batch 5 owns that.
- Do not rename existing `intric.*` Python imports/modules/packages to `eneo.*`.
- Do not create `eneo.*` Python aliases or dual import namespaces.
- Do not modify unrelated dirty files:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- Do not push, open a PR, stage, or commit without explicit user approval.
