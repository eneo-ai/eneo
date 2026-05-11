# T018 Review Checkpoint Open Terminalization Race

## Plan Gate Response

Claude iteration 1 returned `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted critique:

- Do not leave the repository-vs-executor discrimination mechanism open.
- Do not add an executor-side fresh status check as a second source of truth for whether checkpoint opening is valid.
- Reuse the existing `_return_after_terminalized_step_write(...)` terminal outcome translation.
- Use a deterministic integration harness that terminalizes in a separate committed session immediately before the real checkpoint-open repository call.
- Add a negative test proving non-race review checkpoint errors still propagate.

## Decision

Use a typed repository signal:

```python
class FlowReviewCheckpointRunNotRunningError(BadRequestException):
    ...
```

Raise it from `FlowRunRepository.open_review_checkpoint_for_completed_step(...)` at both existing `flow_review_checkpoint_run_not_running` guard sites.

Rationale:

- `FlowRunRepository` already owns the locked read that decides whether checkpoint opening is allowed.
- The executor should not duplicate that check by fetching the run and interpreting its status before calling the repository.
- A typed exception is cleaner than matching a string error code in executor code.
- Other `BadRequestException` cases must continue to propagate, so the branch stays narrow.

## Executor Behavior

Keep the reviewed-step success path delegated through
`_open_review_checkpoint_for_completed_step(...)`. Inside that executor helper, wrap
only the repository checkpoint-open call.

On `FlowReviewCheckpointRunNotRunningError`:

1. Log `flow_executor.review_open_skipped_run_terminal`.
2. Roll back the checkpoint-open transaction before the terminal outcome reread.
3. Delegate to `_return_after_terminalized_step_write(...)`.
4. Do not create a new helper or second terminal-outcome translator.

The existing commit boundary remains unchanged:

- `_persist_successful_step(...)` commits the completed step result and attempt.
- `_open_review_checkpoint_for_completed_step(...)` then attempts the checkpoint transition in its own repository transaction scope.

This boundary is intentional. Collapsing it would broaden the transaction and is out of scope for this slice.

## Tests

### Integration Red Test

Add the primary proof in `backend/tests/integration/flows/test_flow_review_pause_worker_contract.py`.

Harness:

1. Build a real review-policy flow and run it through the executor.
2. Monkeypatch `FlowRunRepository.open_review_checkpoint_for_completed_step` with a wrapper.
3. The wrapper terminalizes the run in a separate `sessionmanager.session()` using the real `FlowRunTerminalizer`, commits, then calls the original repository method.
4. Before implementation, the original method raises and the worker path fails generically.
5. After implementation, the executor catches only `FlowReviewCheckpointRunNotRunningError` and returns the current terminal outcome.

Cover both terminal statuses:

- `CANCELLED` returns `{"status": "skipped", "reason": "run_cancelled"}`.
- `FAILED` returns `{"status": "failed", "error": "...terminalized..."}`.

Fresh-session assertions:

- run remains terminal,
- reviewed step result remains `COMPLETED` with persisted output from before the race,
- downstream pending step results are closed by the real terminalizer as
  `CANCELLED` or `FAILED`,
- reviewed step attempt remains `COMPLETED`,
- no review checkpoint row exists,
- no `flow_run_review_checkpoint_opened` audit outbox row exists.

### Unit Tests

In `backend/tests/unittests/flows/test_flow_executor_runtime.py`:

- mock review checkpoint open to raise `FlowReviewCheckpointRunNotRunningError`;
- assert executor returns the same terminal outcome path as `_return_after_terminalized_step_write(...)`;
- assert a different `BadRequestException` from checkpoint opening propagates.

## Stop Conditions

Stop and return to Judge if:

- the typed exception would need to move outside allowed files,
- deterministic integration testing requires sleeps or timing guesses,
- the implementation swallows broad `BadRequestException`,
- the implementation adds a new checkpoint/lifecycle service/helper owner,
- fixing the race requires schema, migration, API, frontend, Celery routing, or AI Builder changes.

## Claude Gate

- Iteration 1: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Iteration 2: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Iteration 3 implementation gate: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 9`.

## Implementation Receipt

Changed:

- `FlowRunRepository.open_review_checkpoint_for_completed_step(...)` now raises
  typed `FlowReviewCheckpointRunNotRunningError` at both existing
  `flow_review_checkpoint_run_not_running` guard sites.
- `FlowRunExecutor._open_review_checkpoint_for_completed_step(...)` catches only
  that typed signal, rolls back the checkpoint-open transaction, logs
  `flow_executor.review_open_skipped_run_terminal`, and delegates to the
  existing `_return_after_terminalized_step_write(...)` terminal outcome path.
- Generic/sibling review-open `BadRequestException` paths still propagate.

Verification:

- `cd backend && uv run pytest tests/integration/flows/test_flow_review_pause_worker_contract.py -k 'review and terminal' -q`
  -> `3 passed`
- `cd backend && uv run pytest tests/integration/flows/test_flow_review_pause_worker_contract.py -q`
  -> `7 passed`
- `cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -k 'late_output or terminalized or review' -q`
  -> `2 passed`
- `cd backend && uv run pytest tests/unittests/flows/test_flow_executor_runtime.py -k 'review or terminal or cancelled' -q`
  -> `9 passed`
- `cd backend && uv run pyright src/intric/flows/runtime/executor.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py`
  -> `0 errors, 0 warnings, 0 informations`
- `cd backend && uv run ruff check src/intric/flows/runtime/executor.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py`
  -> `All checks passed`
- `cd backend && uv run ruff format --check src/intric/flows/runtime/executor.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py`
  -> `5 files already formatted`
- `git diff --check` -> passed

Claude P3 follow-ups, deferred out of T018 scope:

- `_run_is_cancelled(...)` in `executor.py` may be cleanup-eligible after the
  terminal outcome helper is now reused by both success-write and review-open
  races.
- Future executor test refactors should reduce brittle `flow_run_repo.get`
  side-effect lists where practical.
- If the review-pause fixture shape grows, adjust the terminalization race test
  to assert reviewed step state separately from all downstream step states.
