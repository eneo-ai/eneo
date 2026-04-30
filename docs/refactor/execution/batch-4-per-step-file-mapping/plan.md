# Batch 4 Plan - Per-Step File Mapping

## Status

Loop Iteration 1 planning. No source, test, migration, or frontend
implementation changes are allowed until this plan exists and passes the
Claude plan review loop.

## Scope

Batch 4 implements the PRD-003 per-step file mapping contract after Batches
1-3. The expected result from `docs/refactor/implementation-order.md` is:
`step_inputs` is canonical; top-level `file_ids` source contract removed;
attempt-scoped input/output file mappings added; client/docs/tests updated.

Explicit non-goals:

- Batch 5 generated frontend type migration, except the narrow
  `frontend/packages/intric-js` run-creation wrapper/test/schema updates
  required by this contract.
- Batch 6 AI Builder contract split.
- Batch 8 step rerun.
- Batch 9 human review pause/edit/resume.
- Broad `intric.*` to `eneo.*` package/import renames.
- Frontend UI work outside the required client wrapper/test surface.

## Carry-Forward Seams From Batch 3

| Seam | Owner batch | Status | Batch 4 impact |
|---|---:|---|---|
| Docker validation availability | Batch 3 / environment | Blocked by host approval policy before `docker ps` executed. | Use local fallback validation and record Docker as environment-blocked, not product-failed. |
| Broad Flow ruff import-order baseline | Batch 3 / Batch 10 cleanup | Five untouched import-order issues remain in Flow files. | Run touched-file ruff only; do not auto-fix unrelated baseline files. |
| Terminalization and durable audit outbox | Batch 3 | Committed and green. | Treat as prerequisite satisfied; do not modify terminalization unless a Batch 4 file-mapping test reveals a direct regression. |
| Stale reconciler transaction boundary | Batch 3 / Batch 10 | Claude non-gating follow-up. | No direct impact; keep carried forward for observability/runtime health work. |
| Terminal-source guard durability | Batch 3 / Batch 10 | Claude non-gating follow-up. | Not part of file mapping. Do not broaden Batch 4 into CI guard scripting. |
| SYSTEM actor fallback observability | Batch 3 / Batch 10 | Claude non-gating follow-up. | Not part of file mapping. |

## Contract Reconciliation

| Source | Requirement | Batch 4 decision |
|---|---|---|
| PRD-003 per-step file mapping | `FlowRunCreateRequest` no longer exposes top-level `file_ids`; `step_inputs` is the only request shape. | Remove `file_ids` from the request model, route forwarding, service command, idempotency fingerprint input, JS wrapper request body, and generated schema patch. |
| PRD-003 removed-shape request | Return error code `flow_run_top_level_file_ids_not_supported` for callers still sending removed top-level `file_ids`. | Add a request-model pre-validation gate before Pydantic ignores unknown fields or reports unrelated body-shape errors. This is a negative API contract only; it must not adapt, migrate, or execute the old shape. |
| PRD-003 runtime resolver | Normalize `step_inputs`, validate ownership, persist snapshot, resolve step input, export evidence. | `flow_run_step_inputs.py` remains the canonical normalization/validation owner. Runtime resolution reads only `step_inputs`; historical top-level `file_ids` is no longer a runtime source. Runtime input evidence keeps step-scoped file lineage; the old output alias `file_ids` is not written for new results. |
| PRD-003 file mapping data model | Immutable JSON snapshot plus attempt-scoped `flow_run_step_input_files` and `flow_run_step_result_files`. | Add relational projection tables and repository write methods. Keep JSON snapshot as the public evidence/idempotency envelope. |
| PRD-004 Phase 7 API hardening | OpenAPI, examples, `intric-js`, frontend, tests, and idempotency derivation remove top-level `file_ids` together. | Update OpenAPI tests, run contract docs, API route description, JS wrapper/tests, and narrow `schema.d.ts` generated-client-sensitive shape. |
| PRD-004 generated clients | Generated-client package naming is deferred to Batch 5. | Do not rename `@intric/intric-js`, package paths, OpenAPI tags, or Python modules. |

## Behavior Pins Before Deletion

These pins land before removing the top-level `file_ids` adapter and deleting fields.

| Pin | Test layer | Expected assertion |
|---|---|---|
| Current `step_inputs` happy path | Backend API/integration: new `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py` plus service unit tests. | A run created with non-contiguous step IDs in `step_inputs` stores only canonical `step_inputs`, validates file ownership, and creates relational `flow_run_step_input_files` rows with stable ordering. |
| Current top-level `file_ids` behavior before removal | Rewrite the existing OpenAPI pin and add API negative test before deleting service adapter. | A real create-run HTTP request containing top-level `file_ids` returns `400` with `code == "flow_run_top_level_file_ids_not_supported"` even when another body field is malformed; OpenAPI no longer exposes the field. |
| Evidence/artifact export with runtime files | Existing `test_flow_evidence_api_contracts.py` / `test_flow_run_evidence.py` plus a focused Batch 4 assertion if needed. | Evidence export still reports runtime file lineage from `runtime_input` and generated artifact details. `generated_file_ids` remains the generated-output key; the output alias `file_ids` is not written or read as a new evidence source. |
| Idempotency fingerprint with runtime file inputs | `backend/tests/unittests/flows/test_flow_run_service.py` and `frontend/packages/intric-js/src/endpoints/flows.test.js`. | Fingerprints derive from normalized `input_payload_json`, `expected_flow_version`, tenant/principal scope, explicit fingerprint algorithm version, and sorted `step_inputs`; same key/same normalized step inputs replays; different step file inputs conflict. |
| Input mapping projection equality | `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py`. | The persisted JSON `step_inputs` snapshot and `flow_run_step_input_files` rows describe the same step/file mapping in deterministic order. |
| Client wrapper behavior | `frontend/packages/intric-js/src/endpoints/flows.test.js`. | `flows.runs.create` sends only `step_inputs`; derived upload-intent idempotency keys are stable under step/file ordering; top-level `file_ids` is rejected with the literal code before a request body is sent. |

## Top-Level `file_ids` Deletion Plan

1. Add the negative API behavior pin for top-level `file_ids` with
   `flow_run_top_level_file_ids_not_supported`. This is removed-shape rejection,
   not compatibility logic.
2. Rewrite OpenAPI pins so `FlowRunCreateRequest` examples and properties use
   `step_inputs` only.
3. Update `FlowRunCreateRequest` to reject the removed raw JSON key before
   normal model parsing and update `flow_run_execution_router.py` to stop
   forwarding `file_ids`.
4. Remove `file_ids` from `FlowRunCreateRequest`.
5. Remove `file_ids` from `FlowRunService.create_run`.
6. Delete `apply_legacy_step_one_adapter` from
   `flow_run_step_inputs.py` after tests prove no internal caller remains.
7. Remove both runtime fallbacks to top-level `file_ids` in
   `runtime/step_input_resolution.py`: the direct typed-IO fallback inside
   `resolve_step_input` and the step-one fallback in
   `_resolve_runtime_requested_ids`.
8. Update `flow_file_upload_service.py` recommended payloads and the
   `FlowInputPolicyPublic.recommended_run_payload` OpenAPI example in
   `flow_models.py` to produce `step_inputs` examples rather than top-level
   `file_ids`.
9. Update `intric-js` wrapper/test and the narrow generated schema patch.
10. Verify AI Builder `file_ids` hits are chat/session attachment metadata or
    `step_input.file_ids` prompt vocabulary, not Flow run-create payloads. Do
    not change Batch 6 AI Builder contract surfaces in this batch.
11. Run a count-proof query/test for historical `flow_runs.input_payload_json`
    rows containing top-level `file_ids`. If rows exist in the validation DB,
    classify them as local/dev cleanup or reset evidence; do not reintroduce
    dual-path compatibility for branch-local data.

No compatibility adapter, runtime fallback, or source-contract dual path will
be kept. The branch has no production Flow users, so local historical rows do
not justify preserving top-level `file_ids` runtime behavior.

## Attempt-Scoped File Mapping Design

### Tables

Add an Alembic migration after `20260430_flow_run_audit_outbox`:

- `flow_run_step_input_files`
- `flow_run_step_result_files`

### Ownership

| Concept | Canonical owner |
|---|---|
| Request normalization and validation | `backend/src/intric/flows/flow_run_step_inputs.py` |
| Run creation transaction and input-file projection writes | `backend/src/intric/flows/application/flow_run_service.py` plus `FlowRunRepository.create` |
| Runtime step input resolution | `backend/src/intric/flows/runtime/step_input_resolution.py` |
| Output-file projection writes | `backend/src/intric/flows/runtime/step_execution_runtime.py` serializes generated/artifact file metadata; `backend/src/intric/flows/runtime/executor.py` calls `FlowRepository.save_step_result`, which persists projection rows in the same transaction that writes the corresponding `FlowStepResults` row. |
| Evidence export read contract | Existing evidence bundle/export owners; keep runtime input lineage and `generated_file_ids` readable while projection rows are added. Do not keep the old output `file_ids` alias as a new write/read surface. |

### Proposed columns and constraints

`flow_run_step_input_files`:

- `flow_run_id`, `flow_id`, `tenant_id`
- `step_id`, `step_order`
- `attempt_no` defaulting to `1` for initial run creation
- `file_id`
- `ordinal`
- composite FKs to `flow_runs(id, tenant_id)` and `flow_runs(id, flow_id)`
- FK to `files(id)`
- unique `(flow_run_id, step_id, attempt_no, file_id)`
- unique `(flow_run_id, step_id, attempt_no, ordinal)`
- indexes on `(tenant_id, file_id)`, `(flow_run_id, step_id, attempt_no)`, and
  `(flow_id, step_id)`

`flow_run_step_result_files`:

- `flow_run_id`, `flow_id`, `tenant_id`
- `step_result_id`
- `step_id`, `step_order`
- `attempt_no` defaulting to `1`
- `file_id`
- `ordinal`
- `source` constrained to domain terms `generated_output` or
  `declared_artifact`
- composite FKs to `flow_runs(id, tenant_id)` and `flow_runs(id, flow_id)`,
  plus FK to `flow_step_results(id)` and `files(id)`
- unique `(flow_run_id, step_id, attempt_no, file_id)`
- unique `(flow_run_id, step_id, attempt_no, ordinal)`
- indexes on `(tenant_id, file_id)`, `(flow_run_id, step_id, attempt_no)`, and
  `(step_result_id)`

Do not add a composite FK to `flow_step_results(flow_run_id, flow_id)` unless
the table first gains a matching unique constraint. The current result table
only guarantees `(flow_run_id, step_id)`, so Batch 4 uses the `step_result_id`
FK plus run-level composite FKs for tenant/flow isolation.

Output projection deduplication rule: one row per file per
`(flow_run_id, step_id, attempt_no)`. If the same file appears in generated
outputs and declared artifacts, store a single row with `source =
"declared_artifact"` because the artifact declaration is the more specific
domain signal.

The existing `files` table does not expose `(id, tenant_id)` as a unique
target. Batch 4 will avoid a cross-table files schema change unless
implementation evidence shows the mapping tables cannot preserve tenant safety
without it. Tenant/principal authorization is therefore enforced before
persistence by `validate_submitted_step_inputs`, and the mapping rows store
tenant/flow/run for query isolation. Carry forward a data-model debt item to
add a composite files uniqueness constraint before any non-Flow writer inserts
mapping rows or before a direct file-mapping endpoint is exposed.

### Migration/count proof

- Migration creates the two tables and indexes.
- Count proof checks:
  - historical top-level request rows:
    `flow_runs.input_payload_json ? 'file_ids'`
  - active queued/running rows with top-level file IDs before removing runtime
    fallback.
- If the validation DB contains active top-level rows, stop and report local
  data cleanup/reset options; do not silently keep the adapter.

### Corruption/version behavior

- New requests store `expected_flow_version` and canonical `step_inputs` in
  `flow_runs.input_payload_json`.
- Historical local payloads may still contain top-level request `file_ids`, but
  runtime execution for new requests must not use them as a source. Runtime
  input evidence continues to expose step-scoped `runtime_input.file_ids`;
  generated output evidence uses `generated_file_ids` and declared artifacts,
  not the removed output alias `file_ids`.
- Malformed `step_inputs` continues to fail with named Flow run input errors
  before run creation.

## Runtime Resolver Contract

| Phase | Batch 4 behavior |
|---|---|
| Normalize `step_inputs` | `normalize_step_inputs_payload` returns sorted step IDs and sorted file IDs so fingerprinting and persistence are stable. |
| Validate file ownership | `validate_submitted_step_inputs` continues to check user/service-key ownership and MIME/limit policy before run creation. |
| Persist snapshot | Run creation writes canonical `step_inputs` into `input_payload_json` and `flow_run_step_input_files`; it no longer writes top-level `file_ids`. |
| Resolve step input | Both runtime fallback paths stop reading top-level `input_payload_json["file_ids"]`. `_resolve_runtime_requested_ids` reads only `input_payload_json["step_inputs"][step_id]["file_ids"]`; `_resolve_requested_step_files` receives explicit step-scoped requested IDs only. |
| Export evidence | Runtime step result input payloads continue to carry `runtime_input` metadata, and evidence export continues to expose runtime file lineage. Output artifacts remain readable from `generated_file_ids` and declared artifacts while result-file projection rows are added; the output alias `file_ids` is removed. |

## Idempotency Changes

Fingerprint fields:

- literal `request_fingerprint_algo_version: 1`
- `tenant_id`
- principal scope: exactly one of `user_id` or `service_key_id`
- `flow_id`
- resolved published `flow_version`
- normalized `input_payload_json` excluding transport-only fields
- canonical `step_inputs` sorted by step ID and file ID

The algorithm version is explicit so future request-contract changes can bump
the fingerprint deliberately. Top-level `file_ids` is rejected before
fingerprinting and is never normalized into this hash.

Duplicate delivery behavior:

- Same idempotency key and same normalized payload returns the existing run.
- Same idempotency key and different normalized payload returns
  `flow_run_idempotency_conflict`.
- Top-level `file_ids` is rejected before idempotency replay, because it is no
  longer part of the accepted request contract.

## API And Client Impact

| Surface | Impact |
|---|---|
| Request schema | Remove `FlowRunCreateRequest.file_ids`; examples use `step_inputs`. |
| Response/error shape | Existing successful `FlowRunPublic` remains unchanged. Removed-shape requests return canonical `GeneralError` with `code == "flow_run_top_level_file_ids_not_supported"`. |
| OpenAPI | `FlowRunCreateRequest` properties, operation description, and 400 response description change. This is generated-client-sensitive. |
| Reserved run payload keys | Reject `expected_flow_version`, `file_ids`, and `step_inputs` inside `input_payload_json`; otherwise callers can bypass the canonical request field and validation/projection path. |
| `intric-js` | Update run creation body, upload-intent fingerprint helper, JSDoc, and tests. Reject top-level `file_ids` and reserved inline payload keys in wrapper input; do not silently drop them. Do not rename package or perform Batch 5 type migration. |
| Generated schema | Apply a narrow `frontend/packages/intric-js/src/types/schema.d.ts` patch matching the backend schema delta if full regeneration causes unrelated churn, as Batch 1 did. |
| Docs/examples | Update API descriptions and upload policy recommended payloads. Keep AI Builder chat/session `file_ids` untouched because those are attachment metadata, not Flow run-create inputs. No broad product docs pass. |

## Exact Files Expected To Change

Backend source:

- `backend/src/intric/database/tables/flow_tables.py`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/flow_file_upload_service.py`
- `backend/src/intric/flows/flow_run_evidence.py`
- `backend/src/intric/flows/flow_run_export_json.py`
- `backend/src/intric/flows/flow_run_step_inputs.py`
- `backend/src/intric/flows/infrastructure/flow_repo.py`
- `backend/src/intric/flows/infrastructure/flow_run_repo.py`
- `backend/src/intric/flows/runtime/executor.py`
- `backend/src/intric/flows/runtime/step_execution_runtime.py`
- `backend/src/intric/flows/runtime/step_input_resolution.py`

Backend migration:

- `backend/alembic/versions/20260430_flow_step_file_mappings.py` (new; exact
  revision ID may change only to avoid collision)

Backend tests:

- `backend/tests/integration/flows/test_flow_step_file_mapping_contract.py` (new)
- `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/unittests/flows/test_flow_file_upload_service.py`
- `backend/tests/unittests/flows/test_flow_models.py`
- `backend/tests/unittests/flows/test_flow_router.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unittests/flows/test_step_execution_runtime.py`
- `backend/tests/unittests/flows/test_typed_io_executor.py`
- `backend/tests/unittests/flows/test_typed_io_run_service.py`

Frontend package:

- `frontend/packages/intric-js/src/endpoints/flows.js`
- `frontend/packages/intric-js/src/endpoints/flows.test.js`
- `frontend/packages/intric-js/src/types/schema.d.ts`

Batch docs:

- `docs/refactor/execution/batch-4-per-step-file-mapping/plan.md`
- `docs/refactor/execution/batch-4-per-step-file-mapping/journal.md`
- later loop artifacts: `validation-{N}.log`, `retrospective-{N}.md`,
  `claude-attack-{N}.md`, `claude-reconciliation-{N}.md`

## Do-Not-Touch List

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- Any broad frontend UI files outside the required `intric-js` wrapper/test
  surface.
- Python package/module namespace renames from `intric.*` to `eneo.*`.
- `eneo.*` alias modules or dual import namespaces.

## Validation Commands

Implementation-order Batch 4 labels:

```text
API file mapping contract; runtime resolver test; migration/count proof; client wrapper test
```

Operationalized exact commands for this iteration:

```bash
git diff --check -- \
  backend/src/intric/database/tables/flow_tables.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/src/intric/flows/api/flow_run_execution_router.py \
  backend/src/intric/flows/application/flow_run_service.py \
  backend/src/intric/flows/flow_file_upload_service.py \
  backend/src/intric/flows/flow_run_evidence.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/flow_run_step_inputs.py \
  backend/src/intric/flows/infrastructure/flow_repo.py \
  backend/src/intric/flows/infrastructure/flow_run_repo.py \
  backend/src/intric/flows/runtime/executor.py \
  backend/src/intric/flows/runtime/step_execution_runtime.py \
  backend/src/intric/flows/runtime/step_input_resolution.py \
  backend/alembic/versions/20260430_flow_step_file_mappings.py \
  backend/tests/integration/flows/test_flow_step_file_mapping_contract.py \
  backend/tests/integration/flows/test_flow_runtime_worker_contract.py \
  backend/tests/integration/flows/test_flow_consumer_api_contract.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  backend/tests/unittests/flows/test_flow_file_upload_service.py \
  backend/tests/unittests/flows/test_flow_models.py \
  backend/tests/unittests/flows/test_flow_router.py \
  backend/tests/unittests/flows/test_flow_run_service.py \
  backend/tests/unittests/flows/test_step_execution_runtime.py \
  backend/tests/unittests/flows/test_typed_io_executor.py \
  backend/tests/unittests/flows/test_typed_io_run_service.py \
  frontend/packages/intric-js/src/endpoints/flows.js \
  frontend/packages/intric-js/src/endpoints/flows.test.js \
  frontend/packages/intric-js/src/types/schema.d.ts \
  docs/refactor/execution/batch-4-per-step-file-mapping
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run alembic heads
```

```bash
cd backend && uv run alembic heads
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  -q
```

```bash
cd backend && uv run pytest \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  -q
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pytest \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_flow_models.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_typed_io_run_service.py \
  tests/unittests/flows/test_flow_file_upload_service.py \
  tests/unittests/flows/test_flow_router.py \
  -q
```

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_flow_models.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_typed_io_run_service.py \
  tests/unittests/flows/test_flow_file_upload_service.py \
  tests/unittests/flows/test_flow_router.py \
  -q
```

```bash
docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run pyright \
  src/intric/database/tables/flow_tables.py \
  src/intric/flows/api/flow_models.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/flow_file_upload_service.py \
  src/intric/flows/flow_run_evidence.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_step_inputs.py \
  src/intric/flows/infrastructure/flow_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/step_execution_runtime.py \
  src/intric/flows/runtime/step_input_resolution.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_file_upload_service.py \
  tests/unittests/flows/test_flow_models.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_typed_io_run_service.py
```

```bash
cd backend && uv run pyright \
  src/intric/database/tables/flow_tables.py \
  src/intric/flows/api/flow_models.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/flow_file_upload_service.py \
  src/intric/flows/flow_run_evidence.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_step_inputs.py \
  src/intric/flows/infrastructure/flow_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/step_execution_runtime.py \
  src/intric/flows/runtime/step_input_resolution.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/flows/test_flow_runtime_worker_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_file_upload_service.py \
  tests/unittests/flows/test_flow_models.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_typed_io_run_service.py
```

```bash
cd frontend && ./node_modules/.bin/vitest run packages/intric-js/src/endpoints/flows.test.js
```

```bash
rg -n "file_ids=run_in\\.file_ids|apply_legacy_step_one_adapter|FlowRunCreateRequest.*file_ids|Submit the returned uploaded files as `file_ids`|\"file_ids\".*FlowRunCreateRequest|flow_run_legacy_step_input_unsupported|payload\\.get\\(\"file_ids\"" \
  backend/src/intric/flows \
  backend/tests \
  frontend/packages/intric-js/src/endpoints/flows.js \
  frontend/packages/intric-js/src/endpoints/flows.test.js \
  frontend/packages/intric-js/src/types/schema.d.ts
```

Expected after implementation: no top-level run-create `file_ids` source
contract remains. Remaining `file_ids` hits must be step-scoped,
AI Builder/chat-file unrelated, runtime input evidence metadata, or typed IO
step payload fields.

```bash
cd backend && uv run ruff check \
  src/intric/database/tables/flow_tables.py \
  src/intric/flows/api/flow_models.py \
  src/intric/flows/api/flow_run_execution_router.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/flow_file_upload_service.py \
  src/intric/flows/flow_run_evidence.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_step_inputs.py \
  src/intric/flows/infrastructure/flow_repo.py \
  src/intric/flows/infrastructure/flow_run_repo.py \
  src/intric/flows/runtime/executor.py \
  src/intric/flows/runtime/step_execution_runtime.py \
  src/intric/flows/runtime/step_input_resolution.py \
  tests/integration/flows/test_flow_step_file_mapping_contract.py \
  tests/integration/flows/test_flow_consumer_api_contract.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_file_upload_service.py \
  tests/unittests/flows/test_flow_models.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/unittests/flows/test_step_execution_runtime.py \
  tests/unittests/flows/test_typed_io_executor.py \
  tests/unittests/flows/test_typed_io_run_service.py
```

If Docker remains blocked, classify Docker-only failures as environment issues
and use the local fallback commands above.

## Acceptance Criteria

From PRD-003:

- [ ] `FlowRunCreateRequest` no longer exposes top-level `file_ids`.
- [ ] Create-run accepts canonical step-scoped input only.
- [ ] Create-run rejects reserved orchestration keys inside
      `input_payload_json` so `step_inputs` cannot bypass the canonical
      request field.
- [ ] Per-step file mapping is covered by API/runtime tests.

From PRD-004 Phase 7 API hardening:

- [ ] OpenAPI, examples, `intric-js`, frontend-generated schema, tests, and
  idempotency derivation remove top-level `file_ids` together.
- [ ] Clients still sending top-level `file_ids` receive
  `flow_run_top_level_file_ids_not_supported`; no generic validation text.
- [ ] Idempotency fingerprint includes canonical payload, normalized
  `step_inputs`, principal scope, flow/version, and algorithm version.
- [ ] Runtime input evidence keeps step-scoped file lineage, generated output
  evidence uses `generated_file_ids` and declared artifacts, and new request
  docs do not advertise removed top-level request keys.
- [ ] Generated-client/package naming remains deferred to Batch 5.

## Stop Conditions To Watch

- OpenAPI/schema changes require broad generated type regeneration beyond the
  narrow `intric-js` schema patch.
- Runtime resolver needs UI or generated frontend type migration beyond wrapper
  tests.
- Count proof finds active queued/running old-shape rows; stop and ask whether
  to backfill or defer deletion rather than preserving a compatibility adapter.
- Claude identifies accepted/partial findings after implementation review.
