# Batch 1 — API Source Truth Journal

## Status
GREEN_COMMIT_BOUNDARY_READY

## Iteration Log

### Iteration 1

- Plan: `docs/refactor/execution/batch-1-api-source-truth/plan.md`
- Validation: local fallback validation passed; Docker validation blocked by host tool policy before container inspection.
- Retrospective: `docs/refactor/execution/batch-1-api-source-truth/retrospective-1.md`
- Claude review:
  - Iteration 1: `.codex/artifacts/claude-peer-loop-batch-1-api-source-truth-plan-20260429T193027Z.md`
- Claude verification:
  - Iteration 2: `.codex/artifacts/claude-peer-loop-batch-1-api-source-truth-plan-20260429T193623Z.md`
  - Result: `GREEN_LIGHT: yes`, with low-severity planning polish only.
- Claude implementation review:
  - Iteration 3: `.codex/artifacts/claude-peer-loop-batch-1-api-source-truth-implementation-20260429T195651Z.md`
  - Result: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`, no blocking findings.
- Claude reconciliation:
  - `docs/refactor/execution/batch-1-api-source-truth/claude-reconciliation-1.md`
- Reconciliation: complete for `/plan` and implementation review.
- Outcome: commit boundary ready; no files staged or committed.

## Implementation Summary

- Added `OffsetPaginatedResponse[T]` in `backend/src/intric/main/models.py` and moved Flow list/run-list response models to that opt-in contract.
- Updated Flow authoring and run-list routes to over-fetch `limit + 1`, return only the requested page, and expose required `has_more`.
- Removed the Flow upload-specific OpenAPI postprocessor from `backend/src/intric/server/main.py`; upload schema ownership now stays with the FastAPI route/signature.
- Kept the global WSO2, `NOT_PROVIDED`, SSE, and AI Builder tag postprocessors in `server/main.py`; `_retag_flow_ai_builder_operations` remains a Tier B routing-composition cleanup.
- Documented evidence export as a route-owned JSON attachment with `FlowRunEvidenceExportResponse` and `Content-Disposition`, and validated the export payload before returning the raw `Response`.
- Clarified idempotency retention semantics in route/header descriptions without adding TTL columns or retention migrations.
- Added an API-level consumer integration contract for published-flow discovery, idempotent start/replay/conflict, run listing with `has_more`, polling, and step output retrieval.
- Updated `frontend/packages/intric-js` wrapper behavior for `published.get()` and run-create body construction so `flow_id` remains an idempotency-intent field but is not sent in the request body.
- Updated generated-client-sensitive schema output for the two Flow pagination components and evidence export attachment header. A full local schema regeneration produced broad unrelated churn, so it was reverted and replaced with a targeted patch for the backend OpenAPI delta observed in this batch.
- Added `docs/refactor/api-maintainer-playbook.md` as the durable PRD-004 maintainer handoff.

## Validation Results

- Docker preferred mode:
  - `docker ps --format '{{.Names}}'`
  - Result: blocked before execution by the host tool policy: `approval required by policy, but AskForApproval is set to Never`.
  - Classification: environment/tooling limitation, not a product regression.
- `git diff --check -- backend/src/intric/main/models.py backend/src/intric/server/main.py backend/src/intric/flows/api backend/tests/unit/test_flow_openapi_contract.py backend/tests/integration/flows/test_flow_consumer_api_contract.py backend/tests/integration/flows/test_flow_evidence_api_contracts.py backend/tests/unittests/flows/test_flow_router.py frontend/packages/intric-js/src/endpoints/flows.js frontend/packages/intric-js/src/endpoints/flows.test.js frontend/packages/intric-js/src/types/schema.d.ts docs/refactor/api-maintainer-playbook.md docs/refactor/execution/batch-1-api-source-truth`
  - Result: passed.
- `rg -n "flow_upload_operation|/api/v1/flows/\{id\}/files/|Body_upload_flow_file" backend/src/intric/server/main.py`
  - Result: no matches; the Flow upload OpenAPI rewrite no longer lives in `server/main.py`.
- `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/unittests/flows/test_flow_router.py -q`
  - Result: `116 passed, 24 warnings`.
- `cd backend && uv run pyright src/intric/main/models.py src/intric/server/main.py src/intric/flows/api/flow_upload_router.py src/intric/flows/api/flow_run_evidence_router.py src/intric/flows/api/flow_authoring_router.py src/intric/flows/api/flow_run_execution_router.py src/intric/flows/api/flow_models.py tests/unit/test_flow_openapi_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/unittests/flows/test_flow_router.py`
  - Result: `0 errors, 0 warnings, 0 informations`.
- `cd frontend && ./node_modules/.bin/vitest run packages/intric-js/src/endpoints/flows.test.js`
  - Result: `13 tests passed`.
- `rg -n "Batch 1|batch-1|P0\.|A\.[0-9]|/tmp/ai_builder|plan/(phases|briefs|intents|reviews|codex|progress|architecture_plan)" ...touched source/test/generated files...`
  - Result: no matches.

## Carry-Forward Risks From Batch 0

- Runtime worker contract still executes `FlowRunExecutor` directly instead of the Celery task wrapper. Batch 3 / PRD-003 should add an eager Celery/task-wrapper contract.
- Runtime worker contract imports private `_enable_autobegin_for_flow_task_session`; Batch 3 should expose a public helper/fixture during runtime cleanup.

## Batch 1 Planning Notes

- Docker inspection command `docker ps --format '{{.Names}}' | sort` was attempted during planning and was rejected by the current host approval policy even though approval mode is `never`. Batch validation will still list the Docker-preferred commands from the protocol and will run local fallbacks if Docker remains blocked.
- Claude challenged the first draft plan on pagination ownership, evidence export OpenAPI mechanics, generated-client sensitivity, idempotency retention semantics, AI Builder tag postprocessing, and test fixture ownership.
- The plan was revised before implementation:
  - Use a reusable `OffsetPaginatedResponse[T]` in `backend/src/intric/main/models.py` for Flow list routes only, instead of adding Flow-local page schemas or mutating `PaginatedResponse`.
  - Rewrite the existing Flow pagination OpenAPI pin before changing route response models.
  - Keep evidence export runtime behavior as JSON attachment, but move schema/header documentation to route-owned `responses` and validate the payload against `FlowRunEvidenceExportResponse`.
  - Document/test current row-retention-based idempotency replay semantics without adding a TTL migration in this batch.
  - Keep `_retag_flow_ai_builder_operations` in this batch; parent router tag inheritance makes this broader than the upload/evidence source-truth cleanup.
  - Extract a narrow shared integration fixture only if the new consumer contract would otherwise import helpers from another test module.
- Frontend caller audit:
  - `rg -n "flows\\.list|flows\\.runs\\.list|FlowSparsePublic|FlowRunPublic|\\bcount\\b" frontend/apps/web frontend/packages/intric-js/src/endpoints/flows.test.js`
  - Relevant list consumers inspected:
    - `frontend/apps/web/src/lib/features/flows/FlowsManager.ts` uses `result.items ?? result`.
    - `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/+page.ts` uses `flowsData.items ?? flowsData`.
    - `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte` uses `result.items ?? result`.
  - No frontend app caller was found that directly depends on `PaginatedResponse_FlowSparsePublic_`, `PaginatedResponse_FlowRunPublic_`, or Flow list `count`.
- Existing unrelated dirty files remain untouched:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`

## Decisions Made During This Batch That Might Affect Future Batches

- Generated-client/package naming remains deferred to Batch 5 even if Batch 1 updates generated schema components for Flow pagination.
- AI Builder tag policy/routing composition remains a later API/branding cleanup; Batch 1 should not broaden beyond PRD-004 upload/evidence/pagination/client basics.
- Explicit idempotency TTL/storage migration is not part of Batch 1; current semantics are tied to the retained `flow_runs` row.
- `OffsetPaginatedResponse` should be consolidated if another module adopts the same `has_more` contract; until then it is an opt-in Flow pagination contract to avoid changing unrelated `PaginatedResponse` output.
- `_retag_flow_ai_builder_operations` should be deleted when AI Builder routing moves to a tag composition that does not inherit the parent Flow tag.

## Carry-Forward Risks From Batch 1

- Docker validation could not run in this thread because the host tool policy rejected `docker ps` before execution. Local backend/frontend validation passed.
- `frontend/packages/intric-js/src/types/schema.d.ts` was manually patched to match this batch's narrow OpenAPI delta after full local regeneration produced unrelated churn. Batch 5 still owns the generated-client/package naming and full generated-type cleanup.
- `OffsetPaginatedResponse` is intentionally narrow. If another API surface adopts `has_more`, consolidate pagination contracts instead of proliferating more page response types.
- `_retag_flow_ai_builder_operations` remains in `server/main.py` until AI Builder route/tag composition can own tags without postprocessing.
- Idempotency replay remains tied to retained `flow_runs` rows. Runtime/data retention work must treat any TTL/deletion change as a public-contract change.
- Route functions currently include literal `count` values in returned dictionaries even though `PaginatedResponse.count` is computed from `items` during FastAPI response serialization. The literals match `len(items)` and keep direct router tests readable; future pagination consolidation should remove the redundancy or convert `count` to a normal field.
- Batch 5 should start generated-client work by regenerating `schema.d.ts` cleanly and reconciling it against this batch's targeted manual delta.

## Claude Final Review Answers

- `OffsetPaginatedResponse.count` is inherited from `PaginatedResponse` as a computed field. FastAPI response-model serialization emits `count == len(items)`; the API integration test asserts the serialized list response has `count == 1`, `len(items) == 1`, and `has_more is True`. The returned dicts keep an explicit matching count for direct router tests, but future pagination cleanup should avoid the redundancy.
- The `schema.d.ts` diff is limited to the narrow generated-client-sensitive OpenAPI delta: the two Flow pagination component names/properties, the two Flow list response refs, and the evidence export `Content-Disposition` header.
- `FlowRunPublic` exposes `tenant_id` in the public schema (`backend/src/intric/flows/api/flow_models.py`), so the integration test is admin-scoped by fixture but not relying on an admin-only field projection.
- Docker validation did not run. The first Docker inspection command was blocked by host tool policy before execution, so local validation is the recorded fallback.
- Frontend caller audit found app callers using `items` fallbacks rather than generated pagination component names or `count`; `count` semantics remain current-page count.
