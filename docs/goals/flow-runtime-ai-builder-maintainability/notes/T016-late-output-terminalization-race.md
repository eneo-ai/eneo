# T016 Late Output Terminalization Race

## Plan Gate Response

Claude iteration 1 returned `changes_required` because the Worker plan did not specify the atomic guard owner, return contract, deterministic test harness, or the disposition of the post-provider `CANCELLED` branch. This note answers those decisions before source edits.

## Decision

Use **Option A** from Claude's review: deepen the existing `FlowRepository.save_step_result` writer rather than introduce a second result writer in `FlowRunRepository`.

Rationale:

- `FlowRepository.save_step_result` already owns `flow_step_results` persistence and result-file-row replacement.
- The invariant being added is a write invariant: late provider output must not mutate a step result or its file rows after the parent run has been terminalized.
- Adding a second `complete_step_if_active` writer in `FlowRunRepository` would create two paths writing the same tables unless this slice also migrated all callers and narrowed/deleted the old writer, which is too broad for this P0.
- `FlowRunTerminalizer` remains the owner of terminal lifecycle mutation. The new guard only refuses stale writes; it does not terminalize anything.

## Guard Contract

Change `FlowRepository.save_step_result(...)` to return `FlowStepResult | None`.

The guard is unconditional for normal `step_id` writes. There is no opt-in flag.

The step-result update must be atomic:

- update only when the parent run is active,
- return the saved `FlowStepResult` on write,
- return `None` when the write is guarded because the parent run is already terminal,
- skip result-file-row deletion/replacement when guarded.

The guard is based on the parent `flow_runs.status`, not the current `flow_step_results.status`.

Rationale:

- The bug is parent-run lifecycle drift: late output after a terminalized run must not mutate result or file rows.
- Webhook delivery success/failure legitimately updates a `COMPLETED` step result while the parent run is still active, so gating only on step-result `PENDING/RUNNING` would break current intended behavior.
- If the run is terminal, no step-result or result-file-row write should proceed, regardless of the existing step-result status.

The legacy `result.step_id is None` path is out of scope for this guard because it is not the runtime claimed-step path and does not own generated result-file rows. This exception must remain local to that legacy branch, not a caller-controlled compatibility flag.

## Executor Call-Site Behavior

The executor has these `save_step_result` call sites:

- `_handle_attempt_start_failure`: ignore the return. If another transaction already terminalized the run, terminalization will no-op and the method still returns a failure result without reopening state.
- `_handle_typed_step_failure`: same as above.
- `_handle_generic_step_failure`: same as above.
- `_persist_successful_step`: interpret `None`. On guarded no-op, skip `finish_attempt(COMPLETED)`, skip `state.append_completed`, skip review checkpoint opening, skip webhook delivery, skip final outcome terminalization, and return the current terminal run status.
- `_handle_webhook_delivery_failure`: ignore the return because it is already a failure-return path and terminalization will no-op if another terminal state won the race.
- `_mark_webhook_delivery_success`: interpret `None`. On guarded no-op, skip final outcome terminalization and return the current terminal run status.

For a guarded no-op after provider success, the executor should fetch the latest run after the rejected write and return:

- `{"status": "skipped", "reason": "run_cancelled"}` for `CANCELLED`,
- `{"status": "failed", "error": latest_run.error_message or "flow_run_terminalized"}` for `FAILED`,

No `COMPLETED` arm is implemented because the terminalizer does not complete a run while an active step/open attempt exists. If the repository rejects a write but the fresh run read is not `FAILED` or `CANCELLED`, the executor raises `RuntimeError` instead of silently inventing a third lifecycle path.

## Post-Provider CANCELLED Branch

Delete the existing read-then-check lifecycle branch as a guard.

Reason:

- It only handles `CANCELLED`, not `FAILED`.
- It has a TOCTOU window between reading the run status and saving the step result.
- It duplicates lifecycle state decisions that belong in the atomic write guard.

Provenance decision:

- Do not mutate a terminal attempt after the guard rejects late output.
- `record_attempt_start_provenance(...)` already persists requested model/provider/deadline/effective prompt before the provider call.
- Provider output token provenance from a response that arrived after terminalization is intentionally not recorded in this slice because recording it would mutate terminal attempt state after the terminalizer closed it.

## Deterministic Tests

No sleeps or timing guesses.

### Repository Test

Use explicit transaction ordering:

1. Create a running run with a claimed step result and started attempt.
2. Terminalize it in session A and commit.
3. In session B, call `FlowRepository.save_step_result(..., status=COMPLETED, result_file_references=[late_file])`.
4. Assert the return is `None`.
5. In session C, assert the run and step result remain terminal, output payload is unchanged, and result-file rows were not deleted or replaced.

Cover both terminal statuses:

- `CANCELLED`
- `FAILED`

### Executor Test

Use a controlled provider side effect:

1. Create a real runtime worker context with output mode `http_post`.
2. Configure `completion_service.get_response` so it terminalizes the run in a separate committed session before returning a successful provider response.
3. Run the executor normally.
4. Assert from a fresh session:
   - injected terminal run status remains,
   - step result remains terminal, not completed,
   - attempt remains terminal, not completed,
   - result-file rows are not replaced,
   - `_deliver_webhook` is not awaited,
   - no executor-completed audit outbox row is inserted.

Run this for both terminal statuses in one parametrized test unless the harness proves materially different for one status.

### Unit Test Update

Update `test_execute_does_not_persist_step_after_run_cancelled_during_execution` to assert the new contract:

- `flow_repo.save_step_result` is awaited and returns `None`,
- `flow_run_repo.finish_attempt` is not awaited for the late provider output,
- executor returns `{"status": "skipped", "reason": "run_cancelled"}`.

## Type And Maintainability Targets

- New `Any`: 0
- New `cast`: 0
- New `# type: ignore`: 0
- No new service, wrapper, interface, factory, compatibility path, or second terminalization owner.
- No source comments unless one short invariant comment is necessary near the guarded SQL.
- Public API, schema, migrations, frontend, Celery routing, and AI Builder behavior remain out of scope.

## Claude Gate

- Iteration 1: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Iteration 2: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`. Claude rejected the opt-in `require_active_run=False` guard because it would make a canonical write invariant caller-owned. Codex accepted and revised to an unconditional parent-run active-status guard.
- Iteration 3: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Claude accepted the parent-run guard and highlighted three implementation constraints: keep the guard owner in `FlowRepository`, avoid a real `COMPLETED` branch, and document that PostgreSQL `ON CONFLICT DO UPDATE WHERE` guards only the update branch.
- Iteration 4: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Claude found no blockers and requested one P3 docstring clarification on the new `save_step_result` return contract.
- Iteration 5: `green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 9`. Claude confirmed the docstring follow-up and marked the slice commit-ready.

## Implementation Receipt

### Changed Behavior

- `FlowRepository.save_step_result(...)` now returns `FlowStepResult | None`.
- Its docstring now documents that `None` means the parent run is already terminal.
- Normal runtime step-result writes with a `step_id` update the existing preseeded row only when the parent `flow_runs.status` is active.
- If a provider result arrives after another transaction terminalized the run as `cancelled` or `failed`, the repository returns `None` and does not replace `flow_run_step_result_files` rows.
- `FlowRunExecutor._persist_successful_step(...)` treats `None` as a guarded no-op and exits before `finish_attempt(COMPLETED)`, review checkpoint opening, webhook delivery, or final outcome terminalization.
- `FlowRunExecutor._mark_webhook_delivery_success(...)` also treats `None` as a guarded no-op.
- The old post-provider `CANCELLED` read-then-write branch was deleted. It was incomplete (`CANCELLED` only) and had a TOCTOU window.

### SQL Shape And Isolation

The guard uses `INSERT ... ON CONFLICT DO UPDATE ... WHERE EXISTS (...) RETURNING flow_step_results`.

Important nuance: PostgreSQL applies the `WHERE` condition to the `DO UPDATE` arm. The runtime path is covered because `FlowRunRepository.create(...)` pre-seeds a `flow_step_results` row for every runtime step. The insert arm remains relevant only for non-preseeded/legacy-style callers and was not broadened in this slice.

Database isolation evidence:

- `backend/src/intric/database/database.py` creates the async engine without an explicit `isolation_level`, so PostgreSQL's default `READ COMMITTED` applies.
- The tests use separate committed sessions to prove the late writer sees the terminal status before attempting the guarded update.

### Caller Inventory

Source callers of `save_step_result(...)` after implementation:

| Caller | Return handling | Decision |
|---|---|---|
| `FlowRunExecutor._handle_attempt_start_failure` | ignored | Existing failure/terminalization path; no success continuation. |
| `FlowRunExecutor._handle_typed_step_failure` | ignored | Existing failure/terminalization path; no success continuation. |
| `FlowRunExecutor._handle_generic_step_failure` | ignored | Existing failure/terminalization path; no success continuation. |
| `FlowRunExecutor._persist_successful_step` | interpreted | Guarded no-op exits before attempt completion and downstream paths. |
| `FlowRunExecutor._handle_webhook_delivery_failure` | ignored | Existing failure/terminalization path; no success continuation. |
| `FlowRunExecutor._mark_webhook_delivery_success` | interpreted | Guarded no-op exits before final outcome terminalization. |
| Integration tests and repository tests | awaited for side effects or assert `None` | Updated only where the new behavior matters. |

### Verification

Commands run:

```bash
cd backend && uv run pytest tests/integration/flows/test_flow_step_file_mapping_contract.py -k 'late_step_result' -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -k 'late_output_after_terminalization' -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -k 'late_output or terminalized or result_file' -q
cd backend && uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py -q
cd backend && uv run pytest tests/integration/flows/test_flow_step_file_mapping_contract.py -q
cd backend && uv run pytest tests/unittests/flows/test_flow_executor_runtime.py -k 'cancelled or terminal or step_completed or webhook' -q
cd backend && uv run pyright src/intric/flows/runtime/executor.py src/intric/flows/infrastructure/flow_repo.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/integration/flows/test_flow_step_file_mapping_contract.py tests/unittests/flows/test_flow_executor_runtime.py
cd backend && uv run ruff check src/intric/flows/runtime/executor.py src/intric/flows/infrastructure/flow_repo.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/integration/flows/test_flow_step_file_mapping_contract.py tests/unittests/flows/test_flow_executor_runtime.py
cd backend && uv run ruff format --check src/intric/flows/runtime/executor.py src/intric/flows/infrastructure/flow_repo.py src/intric/flows/infrastructure/flow_run_repo.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/integration/flows/test_flow_step_file_mapping_contract.py tests/unittests/flows/test_flow_executor_runtime.py
git diff --check
```

Results:

- Repository red/green proof: `2 passed`.
- Executor late-terminalization proof: `2 passed`.
- Focused runtime worker suite: `2 passed, 5 deselected`.
- Full runtime worker contract: `7 passed`.
- Full step file mapping contract: `4 passed`.
- Focused executor unit suite: `20 passed, 57 deselected`.
- Pyright: `0 errors, 0 warnings, 0 informations`.
- Ruff: passed after formatting two touched files.

### Maintainability Delta

- Canonical ownership: deepened the existing step-result writer instead of introducing a parallel lifecycle writer.
- Fear-of-change reduction: success persistence now has one explicit return contract for "write won" versus "terminal run won."
- Type safety: no new `Any`, `cast`, or `# type: ignore`.
- Error contract quality: no public API error surface changed.
- Test quality: added deterministic fresh-session integration tests for repository and executor behavior.
- Comment quality: no new source comments.
- Complexity: removed an executor read-then-check branch and replaced it with a repository write guard.
- Deletion quality: deleted the `CANCELLED`-only late-output branch after replacing it with broader `FAILED`/`CANCELLED` coverage.
