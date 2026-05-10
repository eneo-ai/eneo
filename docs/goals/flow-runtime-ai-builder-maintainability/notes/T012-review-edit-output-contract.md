# T012 Review Edit Output Contract

## Scope

Harden review checkpoint edits so API clients cannot persist edited payloads that violate the checkpoint output contract.

## Red Test

Added `test_review_checkpoint_edit_validates_output_contract_before_persisting` in `backend/tests/integration/flows/test_flow_review_pause_worker_contract.py`.

The test failed before the fix because `FlowRunService.edit_review_checkpoint` accepted an invalid edited structured payload and allowed persistence.

## Implementation

- `FlowRunService.edit_review_checkpoint` now loads the checkpoint for edit preconditions before persisting.
- `FlowRunService._validate_review_checkpoint_edit_payload` reuses `output_processing.validate_against_contract`.
- Validation runs before checkpoint, step-result projection, or audit outbox mutation.
- `FlowRunRepository.get_review_checkpoint_for_edit` owns the locked lifecycle precondition read and reuses existing run-waiting, revision, and state guards.
- The repository does not import or run schema validation.
- Invalid review edits return `typed_io_contract_violation` with context:
  - `checkpoint_id`
  - `step_id`
  - `step_order`
  - `payload_field`
- Missing `structured` on a contract-backed review checkpoint is rejected explicitly
  with the same typed code and context before the repository persists anything.

## API Consumer Contract

Added `test_flow_review_edit_returns_typed_contract_error_for_invalid_payload` in `backend/tests/integration/flows/test_flow_consumer_api_contract.py`.

The OpenAPI docs for `PATCH /api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/` now document the typed validation error and context fields.

## Verification

- `cd backend && uv run pytest tests/integration/flows/test_flow_review_pause_worker_contract.py -q` -> `5 passed`
- `cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q` -> `4 passed`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py -k 'review_checkpoint' -q` -> `8 passed`
- `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q` -> `41 passed`
- `cd backend && uv run pyright src/intric/flows/application/flow_run_service.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py` -> `0 errors, 0 warnings, 0 informations`
- `cd backend && uv run ruff check src/intric/flows/application/flow_run_service.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py` -> passed
- `cd backend && uv run ruff format --check src/intric/flows/application/flow_run_service.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py` -> passed
- `git diff --check` -> passed

## Claude Review

- Iteration 1 artifact: `.codex/artifacts/claude-peer-loop-t012-review-edit-output-contract-commit-gate-20260510T222243Z.md`
- Verdict: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`
- Codex still accepted Claude's small hardening suggestion to make missing `structured`
  payloads explicit and to preserve the original `TypedIOValidationException` object
  when adding review-checkpoint context.

## Maintainability Delta

- Canonical ownership: service owns API/application validation; repository owns locked lifecycle reads and persistence.
- Fear of change: review edit behavior now has explicit precondition and contract tests, including no-mutation proof.
- Type safety: no new `Any`, `cast`, or `type: ignore` in production code.
- Error contract quality: public API has a stable error code and context fields.
- Test quality: tests assert behavior through database state and HTTP response, not collaborator calls.
- Comment quality: no comments added.
- Complexity: one narrow repository read method; no wrapper service, factory, or parallel validator.
- Deletion quality: not a deletion slice.
