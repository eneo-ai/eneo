# T002 Judge Decision

## TL;DR

- First implementation target: required runtime input enforcement for omitted or empty `step_inputs`.
- No Claude plan gate is required before this Worker because ownership, red-test harness, allowed files, and error behavior are clear.
- Claude remains mandatory at the commit gate after implementation and verification.
- Idempotency fingerprint canonicalization for successful valid requests is explicitly out of scope.
- Worker must stay on `feature/refactor-flows-flowai`, preserve unrelated dirty files, and not push.

## Decision

Select the smallest safe Worker slice: fix `P0-required-step-inputs-omitted`.

The Worker must TDD-fix create-run required runtime input enforcement so a published flow whose run contract marks a runtime step input as required rejects both omitted `step_inputs` and `step_inputs: {}` with the existing typed `flow_run_required_step_input_missing` error.

The Worker must not change valid run creation, successful idempotency fingerprint canonicalization, or any other P0.

## Evidence

- The maintainability board is committed locally in `d6e368d8 Add Flow runtime maintainability board`.
- The branch is `feature/refactor-flows-flowai`; do not push.
- `backend/src/intric/flows/application/flow_run_service.py:459` only loads the published runtime definition and validates step inputs when `step_inputs is not None`.
- `backend/src/intric/flows/flow_run_step_inputs.py:71` normalizes omitted step inputs to `{}`.
- `backend/src/intric/flows/flow_run_step_inputs.py:196` already raises `flow_run_required_step_input_missing` for required runtime input without files.
- `backend/src/intric/flows/api/flow_run_execution_router.py:260` passes omitted `step_inputs` into the service as `None`.
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py:130` already covers the public HTTP publish/create-run/replay/poll flow.

## Allowed Files

- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/flow_run_step_inputs.py`
- `backend/src/intric/flows/api/flow_run_execution_router.py`
- `backend/tests/integration/flows/test_flow_consumer_api_contract.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/unit/test_flow_openapi_contract.py`

Notes:

- `flow_run_service.py` is the likely implementation file.
- `flow_run_step_inputs.py` is allowed only to preserve the pure validator/normalizer as the canonical validation owner.
- `flow_run_execution_router.py` and `test_flow_openapi_contract.py` are allowed only for narrow touched-route error documentation if needed.
- Do not touch `flow_run_contract_service.py`; stop for Judge if the run-contract source itself needs behavior changes.

## Verification

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_consumer_api_contract.py -q
cd backend && uv run pytest tests/unittests/flows/test_flow_run_service.py -k 'create_run and step_inputs' -q
cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q
cd backend && uv run pyright src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py
cd backend && uv run ruff check src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py
cd backend && uv run ruff format --check src/intric/flows/application/flow_run_service.py src/intric/flows/flow_run_step_inputs.py src/intric/flows/api/flow_run_execution_router.py tests/integration/flows/test_flow_consumer_api_contract.py tests/unittests/flows/test_flow_run_service.py tests/unit/test_flow_openapi_contract.py
git diff --check
git status --short --branch
```

## Stop Conditions

- A meaningful red HTTP/API test cannot be written through the existing `client` and `admin_token` integration harness.
- The fix requires files outside the allowed set.
- The run-contract source needs behavior changes.
- The fix requires schema, migration, generated-client, frontend, worker-runtime, or persistence changes.
- The implementation needs create-run idempotency fingerprint canonicalization changes for successful valid requests.
- The implementation starts solving review-edit validation, executor failure persistence, late-output terminalization, cleanup, or frontend error rendering.
- The only failing/proving tests are mock-call assertions.
- The Worker is tempted to add a new service, wrapper, interface, factory, generic helper, or compatibility path.
- The response cannot expose stable `code`, useful `message`, and `context.step_ids` without broader error-contract work.
- Verification fails twice without a clear pre-existing unrelated cause.

## Red-Test Acceptance

- The Worker first demonstrates HTTP tests fail on the current branch for omitted and empty `step_inputs`.
- The failure is real API behavior, not an artificial mock assertion.
- After implementation, omitted and empty `step_inputs` fail identically for required runtime input.
- The error is typed and stable: `flow_run_required_step_input_missing`, message, and `context.step_ids`.
- Optional runtime inputs remain omittable.
- No cleanup or second P0 is bundled.

## Worker Self-Review Questions

- What is the canonical owner of required runtime input validation after the change?
- Did `FlowRunService.create_run` always reuse `normalize_step_inputs_payload` and `validate_submitted_step_inputs` rather than adding a second validation path?
- Did the change keep the published run contract and create-run behavior aligned?
- Did the change avoid successful create-run idempotency fingerprint canonicalization changes?
- Did the change avoid broad rewrites, shallow services, fake interfaces, and speculative abstractions?
- Did the change add behavior tests through the real HTTP route, not mock-call-only tests?
- Did the change introduce any new `Any`, `dict[str, Any]`, casts, type ignores, or stringly status paths? If yes, why is the boundary justified?
- Did the change add or alter comments? If yes, paste them and classify why they explain intent rather than restating code.
- Did the change leave unrelated dirty files unstaged and untouched?
- Does the frontend need a follow-up because this backend error is now newly reachable from real users?

## Claude Plan Gate

Not required for this slice.

Reason: canonical ownership is clear. `FlowRunService.create_run` orchestrates run creation, while `flow_run_step_inputs` owns the pure step-input contract validation. The public error code already exists in the canonical validator. No schema or migration shape is involved. The red-test harness is concrete and real HTTP-based. Allowed files are bounded.

Keep the mandatory Claude commit gate in T004 after T003 implementation and verification, because this is a P0 public API/runtime boundary fix.

## Claude Commit-Gate Challenge Areas

- Does the implementation keep `flow_run_step_inputs` as the single validation owner?
- Do the HTTP tests prove external API behavior rather than fixture internals?
- Are optional runtime input behavior and valid provided-file routing preserved?
- Is OpenAPI/error documentation sufficient without broadening the slice?
- Was idempotency fingerprint canonicalization accidentally changed or silently decided?
- Did the Worker add a helper, wrapper, comment, `Any`, cast, or broad dict shape that should be rejected?
- Does the newly reachable backend error require a queued frontend-visible error-state follow-up?
