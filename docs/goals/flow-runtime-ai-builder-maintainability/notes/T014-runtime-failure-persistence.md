# T014 Runtime Failure Persistence

## TL;DR

- Fixed the runtime durability gap for executor failure terminalization.
- Added fresh-session DB tests for generic step exceptions, typed output validation failures, attempt-start failures, and webhook delivery failures.
- Kept `FlowRunTerminalizer` as the terminal lifecycle owner and `FlowRunExecutor` as the explicit commit/unit-of-work caller.
- Did not change public API contracts, schema, migrations, frontend, Celery routing, or AI Builder behavior.
- Current status before Claude gate: implementation verified locally; awaiting Claude commit gate.

## Problem

`FlowRunExecutor` terminalized failed runs in failure branches but returned without committing the unit of work. `DatabaseSessionManager.session()` does not auto-commit on normal exit, so a worker could report failure while a fresh database session still saw the run as `running`.

Affected branches:

- `FlowRunExecutor._handle_attempt_start_failure`
- `FlowRunExecutor._handle_typed_step_failure`
- `FlowRunExecutor._handle_generic_step_failure`
- `FlowRunExecutor._handle_webhook_delivery_failure`

## Red Test Evidence

Focused red command before the fix:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -k 'failure_persists_failed_state' -q
```

Initial result:

- `test_generic_step_failure_persists_failed_state_for_fresh_sessions` failed because a fresh session saw `run_row.status == "running"` instead of `"failed"`.
- `test_attempt_start_failure_persists_failed_state_for_fresh_sessions` failed because a fresh session saw `run_row.status == "running"` instead of `"failed"`.
- The typed test initially used an incomplete fake response and hit the generic branch. After adding `total_token_count`, it exercised the typed output-parse branch and proved the same persistence path.
- Claude iteration 1 found the same commit gap in the webhook delivery failure branch. The slice was expanded to cover it because it has the same terminalize-and-return lifecycle shape.

The red tests use real database writes and a fresh `sessionmanager.session()` reread for:

- `flow_runs`
- `flow_step_results`
- `flow_step_attempts`
- `flow_run_audit_outbox`

## Implementation

Changed `backend/src/intric/flows/runtime/executor.py` only in the four failure handlers:

- after `_handle_attempt_start_failure` calls `_terminalize_run(...)`, call `await self._commit()`
- after `_handle_typed_step_failure` calls `_terminalize_run(...)`, call `await self._commit()`
- after `_handle_generic_step_failure` calls `_terminalize_run(...)`, call `await self._commit()`
- after `_handle_webhook_delivery_failure` calls `_terminalize_run(...)`, call `await self._commit()`

This mirrors the existing success and cancellation ownership model: terminalization owns lifecycle mutation; executor owns the transaction commit.

## Tests Added

`backend/tests/integration/flows/test_flow_runtime_worker_contract.py` now includes:

- `test_generic_step_failure_persists_failed_state_for_fresh_sessions`
- `test_typed_step_failure_persists_failed_state_for_fresh_sessions`
- `test_attempt_start_failure_persists_failed_state_for_fresh_sessions`
- `test_webhook_delivery_failure_persists_failed_state_for_fresh_sessions`

Each test executes the real executor path, exits the writer session, opens a fresh session, and asserts the persisted run/result/attempt/outbox state. The webhook case preserves the existing evidence semantics: the step result and attempt are completed, while the run is failed with `webhook_delivery_failed` terminal audit evidence.

`backend/tests/unittests/flows/test_flow_executor_runtime.py` received only Ruff format wrapping in existing assertions so the declared T014 format gate is clean.

## Verification

Passed:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -k 'failure_persists_failed_state' -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -q
cd backend && uv run pytest tests/unittests/flows/test_flow_executor_runtime.py -k 'failure or terminal or cancelled' -q
cd backend && uv run pyright src/intric/flows/runtime/executor.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py
cd backend && uv run ruff check src/intric/flows/runtime/executor.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py
cd backend && uv run ruff format --check src/intric/flows/runtime/executor.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py
git diff --check
```

Observed results:

- Focused persistence tests: `4 passed, 1 deselected`
- Full runtime worker contract: `5 passed`
- Executor unit subset: `19 passed, 58 deselected`
- Pyright: `0 errors, 0 warnings, 0 informations`
- Ruff check: passed
- Ruff format check: passed
- `git diff --check`: passed

Warnings are pre-existing Pydantic/testcontainers deprecations outside this slice.

## Maintainability Self-Review

Canonical owner:

- `FlowRunTerminalizer` remains the owner of terminal lifecycle mutation and audit outbox insertion.
- `FlowRunExecutor` remains the unit-of-work caller that commits after terminal lifecycle mutation.
- No transaction ownership moved into repositories or the terminalizer.

Fear-of-change reduction:

- A future maintainer can inspect each terminal failure handler and see the same terminalize-then-commit boundary.
- The tests prove persisted state from a fresh database session instead of only asserting the executor return value or mocks.

Type safety:

- New `Any`: 0
- New `cast`: 0
- New `# type: ignore`: 0
- New broad persisted/API dict boundary: 0

Error contract quality:

- No public API error contract was changed.
- Existing return shapes were preserved, including the typed failure message-based return.

Test quality:

- Tests assert real persisted behavior across sessions and avoid collaborator-call assertions.
- The attempt-start failure test intentionally asserts no attempt row exists when attempt creation fails before persistence.
- The webhook failure test intentionally asserts the run fails while preserving completed step/attempt evidence with `webhook_delivered = false`.

Comment quality:

- Added comments: 0
- Changed comments: 0

Complexity:

- No helper/service/interface/factory was added.
- The code change is four explicit commits at the existing lifecycle boundary.

Deletion quality:

- No deletion in this slice.

Maintainability score estimate after Claude iteration 1 hardening: 9/10.

Reason: this reduces runtime transaction-boundary fear with minimal code and strong behavior tests across all currently known terminal failure handlers. It stops short of changing the broader executor transaction model, which remains a future phase-sized refactor rather than a safe T014 change.

## Anti-Patterns Avoided

- Did not add a second terminalization owner.
- Did not add a read-then-write repository guard; this slice is not the late-output race fix.
- Did not fix only one sibling failure branch.
- Did not add generic wrappers, pass-through services, or compatibility paths.
- Did not change public API behavior or AI Builder behavior.
- Did not use mock-call-only proof for persistence.

## Residual Risks / Follow-Ups

- Late provider success after terminalization remains the separate P0 race slice; this change does not attempt to solve it.
- The public API golden journey remains queued and should include runtime failure status polling/error-read behavior if that endpoint is touched.
- The runtime worker integration setup could later be extracted only if another test needs the same setup; for now it stays local to avoid a premature fixture abstraction.

## Claude Gate

- Iteration 1: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`. Claude found `_handle_webhook_delivery_failure` had the same terminalization-without-commit defect and flagged an unused `step_id` field in the test context.
- Codex disposition: accepted. Added webhook delivery failure persistence coverage, added `await self._commit()` after webhook failure terminalization, removed the unused `step_id` field, and updated this receipt.
- Iteration 2: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 9`.
- Artifact: `.codex/artifacts/claude-peer-loop-t014-runtime-failure-persistence-commit-gate-iteration-2-20260510T225956Z.md`
