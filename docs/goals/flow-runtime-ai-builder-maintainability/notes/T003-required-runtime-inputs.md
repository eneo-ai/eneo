# T003 Required Runtime Inputs Receipt

## Result

Done. `create_flow_run` now validates runtime step input requirements even when the client omits `step_inputs`, using the published flow snapshot and the existing `flow_run_step_inputs` validator.

## Red Test

Added `test_flow_run_create_rejects_missing_required_runtime_step_inputs` in `backend/tests/integration/flows/test_flow_consumer_api_contract.py`.

Observed red behavior before the implementation:

- `POST /api/v1/flows/{id}/runs/` without `step_inputs` returned `201 Created`.
- The same published flow's `GET /run-contract/` advertised one required runtime step input.
- `step_inputs: {}` already exercised the validator path, but omitted `step_inputs` bypassed it.

The first attempted red run exposed a test-harness issue because run dispatch was not stubbed. After applying the same dispatch stub pattern used by the neighboring consumer-contract test, the red failure was the intended `201` instead of typed `400`.

## Implementation

Changed `FlowRunService.create_run` to:

- Keep existing idempotency, concurrency-limit, input-size, and invalid-snapshot error ordering for requests that do not submit step inputs.
- Preserve `_build_preseed_steps` as the owner of granular published-snapshot preseed errors such as `flow_version_invalid_step_order`, `flow_version_invalid_step_identifier`, and `flow_version_missing_step_identifiers`.
- For explicit `step_inputs`, keep the existing behavior of validating the submitted runtime files before idempotent replay or concurrency checks.
- For omitted `step_inputs`, inspect the published snapshot for required runtime step inputs; when present, parse runtime steps and call `validate_submitted_step_inputs` so the existing validator raises `flow_run_required_step_input_missing`.

Changed API documentation to include `flow_run_required_step_input_missing` and `context.step_ids` in the `400` response description for `create_flow_run`, and extended the OpenAPI contract test to lock that in.

## Changed Files

- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `docs/goals/flow-runtime-ai-builder-maintainability/goal.md`
- `docs/goals/flow-runtime-ai-builder-maintainability/notes/codex-goal-prompt.md`
- `docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`
- `docs/goals/flow-runtime-ai-builder-maintainability/notes/T003-required-runtime-inputs.md`

## Verification

Passed:

- `cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py -q`
- `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q`
- `cd backend && uv run pyright src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py`
- `cd backend && uv run ruff check src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py`
- `cd backend && uv run ruff format --check src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py`
- `git diff --check`

`git status --short --branch` shows the intended changed files plus pre-existing unrelated dirty files. The unrelated files remain unstaged and out of scope.

## Maintainability Self-Review

Canonical owner deepened: `FlowRunService.create_run` remains the run-creation orchestrator, and `flow_run_step_inputs.validate_submitted_step_inputs` remains the only runtime step-input validator. No second validator, service wrapper, generic helper, or compatibility branch was added.

Fear-of-change reduction: required runtime inputs are now enforced for omitted `step_inputs` while preserving the existing published-snapshot preseed error contract and the existing ordering for idempotent replay, size, and concurrency failures. A senior engineer no longer has to know that omitted `step_inputs` skips validation.

Type safety: new `Any`: 0. New `cast`: 3, all inside `_definition_has_required_runtime_step_inputs` to narrow untyped JSON from the existing `JsonObject` published-definition boundary. New `# type: ignore`: 0. New dict-shaped persistence/API boundary: 0.

Error contract quality: the actual HTTP response now returns stable `code`, literal `message`, and `context.step_ids` for both omitted `step_inputs` and `{}`. OpenAPI now documents the machine-readable code and context shape.

Test quality: the regression is protected by an HTTP integration test that creates, publishes, inspects the run contract, and exercises both invalid create-run requests. The full `test_flow_run_service.py` suite is also green, including invalid published-snapshot, idempotency, input-size, and concurrency ordering behavior.

Comment quality: no source comments or docstrings were added.

Complexity: no new loop with unbounded fan-in, no new race-prone read/write guard, no schema/migration change, and no idempotency fingerprint behavior change for successful requests. The only new JSON scan is bounded by the number of published steps and runs only in create-run request validation.

Deletion quality: no deletion in this slice.

Maintainability rubric score: `7.5/8`. The only partial point is type-boundary cleanliness: the published definition is still `JsonObject`, so the required-runtime-input detector needs local casts. The broader typed published-definition boundary remains a later board slice.

## Claude Iteration 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 4`.

Valid blockers accepted and fixed:

- The original verification command was too narrow; it hid failing `create_run` unit tests. The receipt and board now use the full `tests/unittests/flows/test_flow_run_service.py`.
- The first implementation parsed runtime steps too early and changed invalid published-snapshot error ordering. The implementation now lets `_build_preseed_steps` preserve existing granular error codes before runtime step validation.
- OpenAPI documented the code but not the `context.step_ids` shape. The route description and OpenAPI test now cover it.
- The integration test checked the code and context but did not pin the message text. It now asserts `Required runtime input files are missing.`

Claude concerns not implemented as part of this slice:

- A curl smoke test was suggested as supplemental. I did not add it because the HTTP integration test already exercises the same public API path through the app test client, and the board verification stays repo-native and repeatable.
- A future idempotency canonicalization slice remains queued separately; this slice intentionally does not decide successful omitted-vs-empty `step_inputs` fingerprint semantics.

## Anti-Patterns Avoided

- Did not add a second validator.
- Did not return a generic error without stable code/context.
- Did not add new `dict[str, Any]` persistence or API bags.
- Did not add a compatibility branch for omitted `step_inputs`.
- Did not silently bundle successful omitted-vs-empty idempotency fingerprint canonicalization.
- Did not touch Flow AI Builder behavior.
- Did not change invalid published-snapshot, idempotency, input-size, or concurrency error ordering.

## Residual Risks / Follow-Up

- Frontend follow-up should be Scout-gated after the backend contract is committed: confirm whether Flow run creation surfaces `flow_run_required_step_input_missing` actionably for normal users and API-driven web apps.
- A separate API behavior decision remains open for successful optional-runtime-input idempotency fingerprint canonicalization of omitted `step_inputs` vs `{}`.
- This slice does not address the remaining P0 candidates: review-edit output-contract validation, executor failure persistence, and late output terminalization.
