# Batch 4 - Per-Step File Mapping Journal

## Status

IMPLEMENTED - Loop Iteration 1 implementation and local fallback validation
are complete. Retrospective and Claude implementation review are still
required before the batch can reach the commit boundary.

## Iteration Log

### Iteration 1

- Start gate:
  - `git log --oneline --max-count=5` shows Batch 3 latest:
    `373fde9d flows: centralize terminalization and audit outbox`.
  - `git status --short` contains only known unrelated dirty files:
    `frontend/packages/ui/src/icons/types.d.ts`,
    `scripts/run_codex_review.sh`, and `PRODUCT.md`.
  - `git diff --cached --name-only` is empty.
- Docker pre-check:
  - Command attempted: `docker ps --format '{{.Names}}'`.
  - Result: blocked by host approval policy before execution:
    `approval required by policy, but AskForApproval is set to Never`.
  - Validation mode for this Codex environment is therefore local fallback
    unless Docker execution becomes available later in the batch.
- Latest Batch 3 handoff inputs:
  - Journal: `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/journal.md`.
  - Latest retrospective:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/retrospective-3.md`.
  - Latest Claude reconciliation:
    `docs/refactor/execution/batch-3-lifecycle-terminalization-audit/claude-reconciliation-3.md`.

## Initial Source Evidence

- `backend/src/intric/flows/api/flow_models.py:410` defines
  `StepRunInput`; `FlowRunCreateRequest` still exposes top-level
  `file_ids` at `backend/src/intric/flows/api/flow_models.py:434`.
- `backend/src/intric/flows/api/flow_run_execution_router.py:61` tells
  clients to submit uploaded files as top-level `file_ids`; the route passes
  `run_in.file_ids` to the service at `:188`.
- `backend/src/intric/flows/application/flow_run_service.py:334` accepts
  service-level `file_ids`; `:388` adapts them into step one; `:408` writes
  top-level `file_ids` into `input_payload_json`.
- `backend/src/intric/flows/flow_run_step_inputs.py:104` owns the current
  top-level `file_ids` step-one adapter and canonical step-input validation helpers.
- `backend/src/intric/flows/runtime/step_input_resolution.py:218` has a
  direct typed-IO fallback to `run.input_payload_json["file_ids"]`;
  `:393` resolves per-step `step_inputs`, then still falls back to top-level
  `file_ids` for step one at `:402`.
- `backend/src/intric/flows/runtime/step_execution_runtime.py:277` writes the
  historical `generated_file_ids` output key and `:278` writes the historical
  output alias `file_ids`; output projection ownership must account for this
  serializer, not only `runtime/executor.py`.
- `backend/src/intric/database/tables/flow_tables.py:486` has a
  `FlowStepResults` unique constraint on `(flow_run_id, step_id)`, not
  `(flow_run_id, flow_id)`, so Batch 4 must not plan an unsupported composite
  FK to that pair.
- `frontend/packages/intric-js/src/endpoints/flows.js:67` and `:101` still
  include top-level `file_ids` in run intent and request body helpers.
- `backend/tests/unit/test_flow_openapi_contract.py:534` intentionally pins
  that OpenAPI still exposes top-level `file_ids`; Batch 4 must rewrite this
  as the deletion pin.
- `backend/tests/unittests/flows/test_typed_io_run_service.py:1` is an old
  top-level `file_ids` service test and should be rewritten or deleted as the
  service contract changes.
- AI Builder verification:
  - `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:203` models
    `SendMessageRequest`; its `file_ids` field is chat/session attachment
    metadata, not Flow run-create top-level `file_ids`.
  - `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1068` persists
    message attachment IDs in conversation metadata, not a Flow run creation
    body.
  - `backend/src/intric/flows/flow_variable_definitions.py:39` defines
    `step_input.file_ids` as a runtime variable shape, which remains valid
    under the step-scoped contract.

## Batch 3 Carry-Forward Risks Consumed Or Preserved

- Docker validation remains blocked in this Codex app environment by host
  approval policy. Batch 4 records the same local fallback before validation.
- Broad Flow ruff still has known untouched import-order issues from Batch 3;
  Batch 4 will run touched-file ruff instead of auto-fixing the broad baseline.
- Terminalization/audit outbox is now committed and available for Batch 4.
  Batch 4 must not reopen the Batch 3 terminalization design.
- Batch 3's non-gating stale-reconciler transaction-boundary follow-up is not
  part of per-step file mapping and stays carried forward.

## Claude Plan Review - Iteration 1

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-plan-20260430T084017Z.md`.
- Verdict: `changes_required`; `GREEN_LIGHT: no`; minimum score `6`.
- Accepted corrections now reflected in `plan.md`:
  - Use `flow_step_results.id` for result-file FK ownership instead of an
    unsupported `(flow_run_id, flow_id)` composite FK.
  - Use domain source terms `generated_output` and `declared_artifact`, with
    a one-row-per-file dedupe rule.
  - Remove both top-level runtime `file_ids` fallback paths.
  - Treat `runtime/step_execution_runtime.py` as the output-payload serializer
    owner for generated/artifact file keys.
  - Include an explicit `request_fingerprint_algo_version` and
    tenant/principal scope in the idempotency fingerprint.
  - Require the `intric-js` wrapper to reject top-level `file_ids` rather than
    silently ignore it.
  - Add a projection-equality behavior pin for JSON `step_inputs` and
    relational input-file rows.
  - Rewrite old top-level `file_ids` service tests into step-scoped
    happy-path and negative-contract pins.
- Partially accepted corrections:
  - Claude flagged AI Builder `file_ids` examples. Local evidence shows those
    hits are chat/session attachment metadata or `step_input.file_ids`
    variable vocabulary, not Flow run-create request bodies. Batch 4 will not
    modify Batch 6 AI Builder contract surfaces unless implementation evidence
    finds an actual run-create example.
  - Claude flagged the lack of a database-enforced `(files.id, tenant_id)` FK.
    Batch 4 keeps tenant/principal checks in `validate_submitted_step_inputs`
    and stores tenant/run/flow on mapping rows; a composite files uniqueness
    constraint remains a data-model debt before any non-Flow writer or direct
    file-mapping endpoint.

## User Clarification During Planning

- The user clarified that Flow has no production users and this work is only on
  the refactor branch, so Batch 4 should not keep legacy compatibility logic.
- Plan adjustment:
  - Keep only a negative API-boundary rejection for removed top-level
    `file_ids` with `flow_run_top_level_file_ids_not_supported`.
  - Do not keep adapters, fallback execution, dual-path request handling, or
    backfills for branch-local data.
  - If count proof finds active old-shape rows in the local validation DB,
    report cleanup/reset options instead of using those rows to justify
    compatibility.

## Claude Plan Verification - Iteration 2

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-plan-verification-20260430T084731Z.md`.
- Verdict: `green`; `GREEN_LIGHT: yes`; minimum score `8`.
- Non-gating nits applied before implementation:
  - Replaced a non-existent helper reference with the actual
    `resolve_step_input` fallback location.
  - Collapsed duplicate count-proof stop-condition wording.
  - Made the `FlowInputPolicyPublic.recommended_run_payload` example update
    explicit.
  - Required output projection rows to be written in the same transaction as
    the corresponding `FlowStepResults` write.
  - Used `request_fingerprint_algo_version: 1`, since this branch has no
    public v1/v2 migration audience.

## Implementation Source Owner Adjustment

- Source inspection after the green plan review showed that completed step
  result persistence is owned by
  `backend/src/intric/flows/infrastructure/flow_repo.py::save_step_result`, not
  `FlowRunRepository`.
- Plan updated so result-file projection writes live with the actual
  step-result write owner and share that transaction.

## Implementation Notes - Iteration 1

- Removed top-level `file_ids` from `FlowRunCreateRequest`, route forwarding,
  service command input, runtime file resolution, JS run creation, and
  generated-client-sensitive schema.
- Added strict API/client rejection for removed top-level `file_ids` using
  `flow_run_top_level_file_ids_not_supported`. This is a negative contract,
  not compatibility or adaptation.
- Added strict backend/client rejection for reserved orchestration keys inside
  `input_payload_json` using `flow_run_reserved_input_payload_key`; this closes
  the bypass where a caller could hide `step_inputs` inside inline payload
  data and skip the canonical request field validation/projection path.
- Added `flow_run_step_input_files` and `flow_run_step_result_files` as
  attempt-scoped relational projections. The JSON `step_inputs` snapshot
  remains the public evidence/idempotency envelope.
- Result-file projection writes are owned by
  `FlowRepository.save_step_result` and run in the same transaction as the
  corresponding `flow_step_results` upsert.
- `intric-js` now derives upload-run idempotency keys from sorted
  step-scoped file IDs only and rejects removed or reserved shapes before
  making requests.

## Validation - Iteration 1

- `cd backend && uv run pytest tests/integration/flows/test_flow_step_file_mapping_contract.py -q`
  - First run failed because the test asserted ORM objects after session
    close; fixed by capturing primitive row snapshots inside the session.
  - Final result: `2 passed, 16 warnings`.
- `cd backend && uv run pytest tests/integration/flows/test_flow_step_file_mapping_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/unit/test_flow_openapi_contract.py -q`
  - Final result after reserved-key fix: `36 passed, 16 warnings`.
- `cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -q`
  - Result: `1 passed, 16 warnings`.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_typed_io_run_service.py tests/unittests/flows/test_flow_file_upload_service.py tests/unittests/flows/test_flow_router.py -q`
  - Product tests are green except one local environment failure:
    `test_document_outputs_generate_downloadable_artifacts[pdf-application/pdf-.pdf]`
    fails because host WeasyPrint cannot load `libgobject-2.0-0`.
  - Current result: `1 failed, 253 passed, 20 warnings`.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_typed_io_run_service.py tests/unittests/flows/test_flow_file_upload_service.py tests/unittests/flows/test_flow_router.py -k 'not document_outputs_generate_downloadable_artifacts' -q`
  - Result: `252 passed, 2 deselected, 20 warnings`.
- `cd frontend && ./node_modules/.bin/vitest run packages/intric-js/src/endpoints/flows.test.js`
  - Final result: `17 tests passed`.
- `cd backend && uv run pyright ...`
  - Result: `0 errors, 0 warnings`.
- `cd backend && uv run ruff check ...`
  - Result: `All checks passed`.
- `cd backend && uv run alembic heads`
  - Result: single head `20260430_flow_step_file_mappings`.
- `git diff --check -- ...`
  - Result: passed.
- Removed-shape grep for top-level `file_ids` execution paths:
  - Result: no matches in `backend/src/intric/flows`, `backend/tests`, or
    the touched `intric-js` wrapper/schema files.

## Claude Implementation Review - Iteration 1

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-implementation-20260430T093259Z.md`.
- Verbatim attack:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-attack-1.md`.
- Reconciliation:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-reconciliation-1.md`.
- Verdict: `changes_required`; `GREEN_LIGHT: no`; minimum score `6`.
- Accepted fixes applied for Iteration 2:
  - top-level `file_ids` rejection moved into `FlowRunCreateRequest`
    pre-validation, with a real API test proving it wins over unrelated body
    shape errors;
  - reserved orchestration keys centralized in `flow_run_step_inputs.py`;
  - output `file_ids` alias removed from new output payload writes and
    evidence/export artifact ID readers;
  - redundant mapping-table single-column run FKs removed;
  - result mapping `attempt_no` default aligned with input mapping;
  - declared artifact source precedence documented where the dedupe overwrite
    happens.
- Rejected finding:
  - Claude asked to revert to `flow_run_legacy_file_ids_not_supported` because
    PRD text still contains that literal. The user clarified during this loop
    that Batch 4 should avoid "legacy" vocabulary/logic for unshipped Flows.
    Per protocol, PRDs are not edited mid-loop; `plan.md` and this journal
    record the human override.

## Focused Revalidation After Iteration 1 Claude Fixes

- `cd backend && uv run pytest tests/unittests/flows/test_flow_models.py::test_flow_run_create_request_rejects_removed_top_level_file_ids tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_run_create_rejects_removed_top_level_file_ids_before_body_shape_errors tests/unittests/flows/test_step_execution_runtime.py::test_build_output_payload_includes_structured_and_artifacts tests/integration/flows/test_flow_runtime_worker_contract.py -q`
  - Result: `4 passed, 16 warnings`.

## Validation - Iteration 2

- Docker pre-check:
  - Command attempted again: `docker ps --format '{{.Names}}'`.
  - Result: still blocked before execution by host approval policy:
    `approval required by policy, but AskForApproval is set to Never`.
  - Validation mode remains local fallback.
- `git diff --check -- ...`
  - Result: passed.
- `cd backend && uv run alembic heads`
  - Result: single head `20260430_flow_step_file_mappings`.
- `cd backend && uv run pytest tests/integration/flows/test_flow_step_file_mapping_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/unit/test_flow_openapi_contract.py -q`
  - Result: `38 passed, 16 warnings`.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_step_execution_runtime.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_typed_io_run_service.py tests/unittests/flows/test_flow_file_upload_service.py tests/unittests/flows/test_flow_router.py -q`
  - Result: `1 failed, 293 passed, 20 warnings`.
  - Failure is the known local WeasyPrint native dependency gap:
    `libgobject-2.0-0` is unavailable for the PDF renderer case
    `test_document_outputs_generate_downloadable_artifacts[pdf-application/pdf-.pdf]`.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_step_execution_runtime.py tests/unittests/flows/test_typed_io_executor.py tests/unittests/flows/test_typed_io_run_service.py tests/unittests/flows/test_flow_file_upload_service.py tests/unittests/flows/test_flow_router.py -k 'not document_outputs_generate_downloadable_artifacts' -q`
  - Result: `292 passed, 2 deselected, 20 warnings`.
- `cd backend && uv run pyright ...`
  - First Iteration 2 run found a validator passthrough typing issue in
    `FlowRunCreateRequest`.
  - Fix: return the validator passthrough as `cast(object, data)`.
  - Final full touched-file rerun result: `0 errors, 0 warnings, 0 informations`.
- `cd frontend && ./node_modules/.bin/vitest run packages/intric-js/src/endpoints/flows.test.js`
  - Result: `17 tests passed`.
- Removed-shape grep:
  - Result: one intentional negative-contract test match in
    `backend/tests/unittests/flows/test_flow_models.py`; no source execution
    path or client request-builder path remains.
- `cd backend && uv run ruff check ...`
  - Result: `All checks passed`.

## Claude Implementation Review - Iteration 2

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-verification-20260430T094959Z.md`.
- Verbatim attack:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-attack-2.md`.
- Reconciliation:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-reconciliation-2.md`.
- Verdict: `green`; `GREEN_LIGHT: yes`; minimum score `8`.
- Accepted low-risk cleanup:
  - removed the remaining defensive `getattr(request, "headers", {})`
    idempotency-key fallback from the create-run route;
  - wrapped the new migration's composite FK names in `op.f(...)` for naming
    convention consistency.
- Rejected non-blocking follow-ups:
  - persisted idempotency algorithm version column;
  - direct-insert consistency guard for denormalized result projection
    `step_id` / `step_order`;
  - broad `extra="forbid"` request-schema hardening;
  - extra empty-vs-omitted `step_inputs` projection pin.

## Validation - Iteration 3

- `git diff --check -- backend/src/intric/flows/api/flow_run_execution_router.py backend/tests/unittests/flows/test_flow_router.py backend/alembic/versions/20260430_flow_step_file_mappings.py docs/refactor/execution/batch-4-per-step-file-mapping`
  - Result: passed.
- `cd backend && uv run alembic heads`
  - Result: single head `20260430_flow_step_file_mappings`.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_router.py::test_create_flow_run_forwards_idempotency_key tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_consumer_runtime_routes_support_start_replay_poll_and_steps -q`
  - Result: `2 passed, 16 warnings`.
- `cd backend && uv run pyright src/intric/flows/api/flow_run_execution_router.py tests/unittests/flows/test_flow_router.py tests/integration/flows/test_flow_consumer_api_contract.py`
  - Result: `0 errors, 0 warnings, 0 informations`.
- `cd backend && uv run ruff check src/intric/flows/api/flow_run_execution_router.py tests/unittests/flows/test_flow_router.py ../backend/alembic/versions/20260430_flow_step_file_mappings.py`
  - Result: `All checks passed`.

## Claude Implementation Review - Iteration 3

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-final-verification-20260430T095528Z.md`.
- Verbatim attack:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-attack-3.md`.
- Reconciliation:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-reconciliation-3.md`.
- Verdict: `green`; `GREEN_LIGHT: yes`; minimum score `8`.
- Accepted verification:
  - Iteration 2 cleanup is verified.
  - `git grep -n "getattr(request" -- 'backend/src/intric/flows/**/*.py'`
    returned no matches.
- Rejected non-blocking item:
  - `test_create_flow_run_handles_missing_headers_object` is now a stale test
    name after header fallback removal. The test still pins absent header
    injection forwarding `None`; carry forward a cosmetic rename rather than
    extending the loop beyond Iteration 3.

## Carry-Forward Risks

- Docker validation through `docker ps` / `docker exec` remains blocked by the
  Codex app approval policy. Local integration tests did run Testcontainers
  PostgreSQL/Redis successfully.
- Host-local WeasyPrint native dependencies are missing
  (`libgobject-2.0-0`), so the PDF artifact unit case fails locally while the
  non-renderer Batch 4 product tests pass.
- The PRD files still contain the originally requested `legacy` error-code
  literal. The user clarified during Batch 4 that removed unshipped Flow
  surfaces should not keep "legacy" vocabulary. Per the loop protocol, PRDs
  were not edited mid-loop; the implementation, plan, and journal use
  `flow_run_top_level_file_ids_not_supported`.
- Cosmetic: `backend/tests/unittests/flows/test_flow_router.py` contains a
  test named `test_create_flow_run_handles_missing_headers_object`; after
  Iteration 3 it actually pins absent idempotency header injection forwarding
  `None`.
- Batch 5 still owns generated frontend type/package migration questions.
