# Batch 9 — Human Review Pause/Edit/Resume Journal

## Status
IN_PROGRESS

## Starting Point

- Branch: `feature/refactor-flows-flowai`
- Previous completed slice: Batch 8 Slice 8.9 committed as `e0c95a9c flows: include rerun lineage in evidence exports`
- Unrelated local files present before Batch 9 work:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
  - `docs/refactor/goals.md`
- Batch 9 directory: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/`
- Docker container selected for validation: `eneo-41ae93-eneo-1`

## Iteration Log

### Iteration 1 — Plan

- Plan: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/plan.md`
- Validation: not run yet
- Claude review: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-20260502T152839Z.md`
- Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-1.md`
- Outcome: plan revised for status naming, CAS/idempotency, payload ownership, webhook ordering, permissions, audit lifecycle ownership, evidence versioning, and frontend status ownership

### Iteration 2 — Plan Verification

- Plan: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/plan.md`
- Validation: not run yet
- Claude review: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-verification-20260502T153942Z.md`
- Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-2.md`
- Outcome: plan revised for checkpoint-revision outbox keys, `started_at` preservation, a separate lifecycle-source rename slice, GET permission semantics, output-mode side-effect classification, and resume transaction ordering

### Iteration 3 — Plan Verification

- Plan: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/plan.md`
- Validation: not run yet
- Claude review: green, artifact `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-verification-2-20260502T155504Z.md`
- Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-3.md`
- Outcome: plan accepted for implementation after adding Claude's non-blocking data-model reviewability nits

### Slice 9.0a — Lifecycle Source Rename

- Source:
  - `backend/src/intric/flows/enums.py`
  - `backend/src/intric/database/tables/flow_tables.py`
  - `backend/src/intric/flows/application/flow_run_terminalization.py`
  - `backend/src/intric/flows/application/flow_dispatch.py`
  - `backend/src/intric/flows/application/flow_run_service.py`
  - `backend/src/intric/flows/infrastructure/flow_run_repo.py`
  - `backend/src/intric/flows/runtime/executor.py`
  - `backend/src/intric/flows/runtime/tasks.py`
- Tests:
  - `backend/tests/unittests/flows/test_celery_runtime.py`
  - `backend/tests/unittests/flows/test_flow_run_service.py::test_cancel_run_marks_pending_steps_cancelled`
  - `backend/tests/integration/flows/test_flow_terminalization_contract.py`
- Local validation:
  - `rg -n "FlowRunTerminalSource|FLOW_RUN_TERMINAL_SOURCE_VALUES" backend/src/intric backend/tests` — passed, no references
  - `.venv/bin/ruff check` on the renamed source/test files — passed after import sorting
  - `uv run pyright` on the renamed source/test files — passed, 0 errors
  - `.venv/bin/pytest tests/unittests/flows/test_celery_runtime.py tests/unittests/flows/test_flow_run_service.py::test_cancel_run_marks_pending_steps_cancelled tests/integration/flows/test_flow_terminalization_contract.py -q` — passed, 16 tests
- Docker validation: blocked before execution by this Codex process with `Rejected("approval required by policy, but AskForApproval is set to Never")`
- Outcome: mechanical rename complete; no enum string values or runtime behavior changed

### Slice 9.1 — Status And Checkpoint Data Model

- Source:
  - `backend/src/intric/flows/enums.py`
  - `backend/src/intric/database/tables/flow_tables.py`
  - `backend/src/intric/flows/domain/flow.py`
  - `backend/src/intric/flows/flow_factory.py`
  - `backend/src/intric/flows/infrastructure/flow_run_repo.py`
  - `backend/src/intric/flows/application/flow_run_terminalization.py`
  - `backend/src/intric/audit/domain/action_types.py`
  - `backend/src/intric/audit/domain/entity_types.py`
  - `backend/src/intric/audit/domain/category_mappings.py`
  - `backend/alembic/versions/20260502_review_checkpoints.py`
- Tests:
  - `backend/tests/unittests/flows/test_flow_run_status_predicates.py`
  - `backend/tests/unittests/flows/test_flow_review_checkpoint_data_model.py`
  - `backend/tests/unittests/flows/test_flow_enums.py`
  - `backend/tests/integration/flows/test_flow_run_review_checkpoint_repository.py`
  - `backend/tests/integration/flows/test_flow_run_rerun_repository.py::test_non_rerunnable_run_status_rejects_without_mutation`
- Local validation:
  - `.venv/bin/ruff check` on Slice 9.1 source/test/migration files — passed
  - `.venv/bin/ruff format --check` on Slice 9.1 source/test/migration files — passed
  - `uv run pyright` on Slice 9.1 source/test/migration files — passed, 0 errors
  - `uv run python -m py_compile alembic/versions/20260502_review_checkpoints.py` — passed
  - `.venv/bin/pytest tests/unittests/flows/test_flow_run_status_predicates.py tests/unittests/flows/test_flow_review_checkpoint_data_model.py tests/unittests/flows/test_flow_enums.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_run_rerun_repository.py::test_non_rerunnable_run_status_rejects_without_mutation -q` — passed, 23 tests
- Docker validation: blocked before execution by this Codex process with `Rejected("approval required by policy, but AskForApproval is set to Never")`
- Claude review:
  - Iteration 1: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-1-review-checkpoint-data-model-20260502T162800Z.md`
  - Iteration 2: green, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-1-review-checkpoint-data-model-verification-20260502T163623Z.md`
  - Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-4.md`
- Outcome: data-model foundation complete; runtime/API producers remain out of scope for Slice 9.2 and later

## Carry-Forward Risks

- Review policy wire shape is pinned as `{"review_policy": {"mode": "view" | "edit"}}`; Slice 9.2 still needs API/schema tests before source implementation.
- Resume CASes the checkpoint and run, moves the run from `awaiting_review` to `queued`, and dispatches the existing `flows.execute` task. Batch 9 should not add a separate `flows.resume` task unless it deletes code.
- Frontend generated type updates must not overwrite unrelated local changes.

## Decisions Made During This Batch

- Runtime review checkpoints are separate from `care_data_policy`, because `care_data_policy` models outside-flow governance metadata.
- `awaiting_review` is planned as non-active, non-terminal, and cancellable.
- Checkpoint TTL auto-cancellation is out of scope by default; reconciliation repairs orphan state only until an ADR/product decision changes this.
- Review-policy steps cannot use any output mode classified by `flow_output_mode_has_outbound_delivery` until reviewed outbound delivery is explicitly designed.
- Review/resume endpoints use `FLOWS_MANAGE` and user principals only for the first implementation.
- The active checkpoint read endpoint uses existing flow view semantics.
- Review checkpoint outbox rows are keyed by checkpoint revision; terminal outbox rows remain keyed by run revision.
- Slice 9.0a is the next implementation slice before checkpoint data-model work.
- Slice 9.1 stores checkpoint `step_id` as a historical UUID and does not FK it to mutable `flow_steps`; Slice 9.2 must validate it against the run's published flow version before checkpoint creation.
- Slice 9.1 makes `awaiting_review` cancellable through terminalization, but active checkpoint closure on run cancellation remains a Slice 9.4 responsibility.
