# Claude Reconciliation 13 — Runtime Rerun Attempt Lineage

## Claude Verdict

- Plan review artifact: `.codex/artifacts/claude-peer-loop-batch-8-runtime-rerun-attempt-lineage-plan-20260502T132651Z.md`
- Plan verdict: changes required
- Verification artifact: `.codex/artifacts/claude-peer-loop-batch-8-runtime-rerun-attempt-lineage-verification-20260502T135535Z.md`
- Verification verdict: green content, but the peer-loop parser rejected Claude's Markdown-prefixed header format.
- Parser-clean verification artifact: `.codex/artifacts/claude-peer-loop-batch-8-runtime-rerun-attempt-lineage-verification-exact-20260502T135952Z.md`
- Parser-clean verification verdict: green
- Green light: yes
- Minimum score: 8

## Accepted Changes

| Claude point | Codex action | Evidence |
|---|---|---|
| Attempt numbers must come from persisted run history, not Celery retry count. | Executor now uses the operation root attempt number for the root rerun step and repository allocation for all other step attempts. | `backend/src/intric/flows/runtime/executor.py`, `backend/src/intric/flows/infrastructure/flow_run_repo.py` |
| `current_attempt_no` must advance only after a successful replacement result is persisted. | `FlowRepository.save_step_result(...)` sets `current_attempt_no` only for completed step results. | `backend/src/intric/flows/infrastructure/flow_repo.py` |
| Predecessor attempts should not be superseded until the replacement attempt completes. | `finish_attempt(...)` marks the predecessor superseded only when the completed attempt has a predecessor. | `backend/src/intric/flows/infrastructure/flow_run_repo.py` |
| Active rerun context should be loaded once and passed through the executor, not queried per step. | Executor loads `get_active_rerun_operation(...)` once and builds a step-id map before the step loop. | `backend/src/intric/flows/runtime/executor.py` |
| Runtime state needs a database backstop against multiple active operations. | Added `uq_flow_run_rerun_operations_one_active_per_run` partial unique index in a forward migration and model metadata. | `backend/alembic/versions/20260502_rerun_runtime_lineage.py`, `backend/src/intric/database/tables/flow_tables.py` |
| Rerun operation terminal status belongs with run terminalization. | Terminalizer closes active rerun operations when a run reaches a terminal state. | `backend/src/intric/flows/application/flow_run_terminalization.py` |
| Rerun completion needs a second terminal audit row for the same run. | `flow_run_audit_outbox` now stores `run_revision` and is unique by `(flow_run_id, run_revision)`. | `backend/alembic/versions/20260502_rerun_runtime_lineage.py`, `backend/src/intric/database/tables/flow_tables.py` |
| `mark_rerun_operation_running(...)` idempotency should be covered. | Added an integration assertion that a second call leaves `started_at` and `root_attempt_id` unchanged. | `backend/tests/integration/flows/test_flow_run_rerun_repository.py` |

## Deferred Points

| Claude point | Decision | Reason |
|---|---|---|
| Add a comment explaining that the root step marks the operation running because executor processing is step-order based. | Deferred. | The code path is readable and the comment would restate current control flow more than explain a durable business invariant. A future parallel-execution change should revisit the lifecycle owner rather than add a comment now. |
| Co-locate the partial unique index in the original rerun table migration. | Deferred. | Earlier Batch 8 migrations are already committed on this branch. A forward migration gives already-upgraded dev databases the same schema as fresh databases. |
| Split the idempotency assertion into a standalone integration test. | Deferred. | The assertion belongs to the existing start-and-lineage lifecycle test and avoids duplicating a large integration fixture. |

## Verification

- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/ruff check alembic/versions/20260502_rerun_runtime_lineage.py src/intric/database/tables/flow_tables.py src/intric/flows/api/flow_models.py src/intric/flows/application/flow_run_terminalization.py src/intric/flows/infrastructure/flow_repo.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/runtime/executor.py tests/integration/flows/test_flow_run_rerun_repository.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_rerun_data_model.py` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pyright --pythonpath .venv/bin/python src/intric/database/tables/flow_tables.py src/intric/flows/api/flow_models.py src/intric/flows/application/flow_run_terminalization.py src/intric/flows/infrastructure/flow_repo.py src/intric/flows/infrastructure/flow_run_repo.py src/intric/flows/runtime/executor.py tests/integration/flows/test_flow_run_rerun_repository.py tests/integration/flows/test_flow_runtime_worker_contract.py tests/unittests/flows/test_flow_executor_runtime.py tests/unittests/flows/test_flow_models.py tests/unittests/flows/test_flow_rerun_data_model.py` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/python -m py_compile alembic/versions/20260502_rerun_runtime_lineage.py` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/alembic heads` — passed, single head `20260502_rerun_runtime_lineage`
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/alembic upgrade head` — passed
- `docker exec -w /workspace/backend eneo-41ae93-eneo-1 .venv/bin/pytest tests/integration/flows/test_flow_runtime_worker_contract.py::test_flow_run_created_by_service_executes_to_terminal_worker_state tests/integration/flows/test_flow_run_rerun_repository.py::test_rerun_attempt_start_and_success_records_lineage tests/integration/flows/test_flow_terminalization_contract.py tests/unittests/flows/test_flow_executor_runtime.py tests/unittests/flows/test_flow_models.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_rerun_data_model.py -q` — passed, 127 tests
- `git diff --check` — passed
- Diff-only forbidden compatibility/session-language grep over backend source, tests, and migrations — no matches

## Decision

Slice 8.8 is ready to commit. The runtime now records rerun attempt lineage from persisted database state, closes rerun operations through terminalization, and preserves terminal audit rows per run revision without adding compatibility paths for unreleased Flow behavior.
