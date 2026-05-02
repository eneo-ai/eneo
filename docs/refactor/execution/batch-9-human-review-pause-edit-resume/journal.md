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

### Slice 9.2 — Review Policy Contract And Checkpoint Open Command

- Source:
  - `backend/src/intric/flows/flow_review_policy.py`
  - `backend/src/intric/flows/enums.py`
  - `backend/src/intric/database/tables/flow_tables.py`
  - `backend/src/intric/flows/domain/flow.py`
  - `backend/src/intric/flows/api/flow_models.py`
  - `backend/src/intric/flows/api/flow_assembler.py`
  - `backend/src/intric/flows/application/flow_service.py`
  - `backend/src/intric/flows/infrastructure/flow_repo.py`
  - `backend/src/intric/flows/infrastructure/flow_run_repo.py`
  - `backend/src/intric/flows/runtime/models.py`
  - `backend/src/intric/flows/runtime/step_definition_parser.py`
  - `backend/src/intric/flows/flow_validators.py`
  - `backend/alembic/versions/20260502_flow_step_review_policy.py`
- Tests:
  - `backend/tests/unittests/flows/test_flow_review_policy.py`
  - `backend/tests/unittests/flows/test_flow_validators.py`
  - `backend/tests/unittests/flows/test_published_definition_contract.py`
  - `backend/tests/integration/flows/test_flow_run_review_checkpoint_repository.py`
- Local validation:
  - `uv run ruff check ...` from `backend/` on Slice 9.2 source/test files — passed
  - `uv run ruff format --check ...` from `backend/` on Slice 9.2 source/test files — passed
  - `uv run pyright ...` from `backend/` on Slice 9.2 source/test files — passed, 0 errors
  - `uv run python -m py_compile alembic/versions/20260502_flow_step_review_policy.py` from repo root — passed
  - `uv run pytest tests/unittests/flows/test_flow_review_policy.py tests/unittests/flows/test_flow_validators.py tests/unittests/flows/test_published_definition_contract.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py -q` from `backend/` — passed, 54 tests
  - `git diff --check` — passed
  - `rg -n "review_policy=\\{" backend/src` — passed, no source matches
- Docker validation: blocked before execution by this Codex process with `Rejected("approval required by policy, but AskForApproval is set to Never")`
- Claude review:
  - Iteration 1: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-2-review-policy-open-command-20260502T165110Z.md`
  - Iteration 2: green, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-2-review-policy-open-command-verification-20260502T170329Z.md`
  - Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-5.md`
- Outcome: typed review-policy contract complete, write-path validation added, and the repository can open a review checkpoint for a completed step idempotently; executor/API wiring remains out of scope for Slice 9.3 and later

### Slice 9.3 — Executor Pause/Yield

- Source:
  - `backend/src/intric/flows/runtime/executor.py`
- Tests:
  - `backend/tests/integration/flows/test_flow_review_pause_worker_contract.py`
  - `backend/tests/integration/flows/test_flow_runtime_worker_contract.py`
  - `backend/tests/integration/flows/test_flow_terminalization_contract.py`
- Local validation:
  - `uv run ruff check ...` from `backend/` on Slice 9.3 source/test files — passed
  - `uv run ruff format --check ...` from `backend/` on Slice 9.3 source/test files — passed
  - `uv run pyright ...` from `backend/` on executor, run repository, and Slice 9.3 test files — passed, 0 errors
  - `uv run pytest tests/integration/flows/test_flow_runtime_worker_contract.py tests/integration/flows/test_flow_review_pause_worker_contract.py tests/integration/flows/test_flow_terminalization_contract.py::test_stale_running_query_excludes_awaiting_review_runs -q` from `backend/` — passed, 3 tests
  - `git diff --check` — passed
  - Anti-slippage grep from the project rules on touched Slice 9.3 files and Batch 9 docs — passed, no matches
- Docker validation: blocked before execution by this Codex process with `Rejected("approval required by policy, but AskForApproval is set to Never")`
- Claude review:
  - Iteration 1: green with low-severity coverage suggestions, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-3-executor-pause-yield-review-20260502T172014Z.md`
  - Iteration 2: green, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-3-executor-pause-yield-review-verification-20260502T172406Z.md`
  - Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-6.md`
- Outcome: executor now opens a review checkpoint after successful review-policy step persistence, returns `awaiting_review`, leaves downstream steps pending, and duplicate task delivery skips the paused run without another checkpoint or model call

### Slice 9.4 — Review API, Edit/Approve/Reject, And Resume Dispatch

- Source:
  - `backend/src/intric/flows/api/flow_run_execution_router.py`
  - `backend/src/intric/flows/api/flow_models.py`
  - `backend/src/intric/flows/api/flow_assembler.py`
  - `backend/src/intric/flows/application/flow_run_service.py`
  - `backend/src/intric/flows/application/flow_run_terminalization.py`
  - `backend/src/intric/flows/infrastructure/flow_run_repo.py`
  - `backend/src/intric/flows/flow_access_policy.py`
- Tests:
  - `backend/tests/unit/test_flow_openapi_contract.py`
  - `backend/tests/unittests/flows/test_flow_access_policy.py`
  - `backend/tests/unittests/flows/test_flow_run_service.py`
  - `backend/tests/integration/flows/test_flow_run_review_checkpoint_repository.py`
  - `backend/tests/integration/flows/test_flow_review_pause_worker_contract.py`
- Local validation:
  - `uv run ruff format ...` from `backend/` on Slice 9.4 source/test files — passed, unchanged after final pass
  - `uv run ruff check ...` from `backend/` on Slice 9.4 source/test files — passed
  - `uv run pyright ...` from `backend/` on Slice 9.4 source/test files — passed, 0 errors
  - `uv run pytest tests/unittests/flows/test_flow_access_policy.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_run_service.py -q` from `backend/` — passed, 174 tests
  - `uv run pytest tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_review_pause_worker_contract.py -q` from `backend/` — passed, 17 tests
- Docker validation: blocked before execution by this Codex process with `Rejected("approval required by policy, but AskForApproval is set to Never")`
- Claude review:
  - Iteration 1: changes required for the Slice 9.4 plan, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-4-review-api-resume-plan-20260502T173550Z.md`
  - Iteration 2: green for the revised Slice 9.4 plan, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-4-review-api-resume-plan-verification-20260502T173937Z.md`
  - Iteration 3: green for implementation, artifact `.codex/artifacts/claude-peer-loop-batch-9-slice-9-4-review-api-resume-implementation-20260502T181025Z.md`
  - Reconciliation: `docs/refactor/execution/batch-9-human-review-pause-edit-resume/claude-reconciliation-7.md`
- Outcome: review checkpoint active read, edit, approve, reject, and resume endpoints are typed and permission-gated; resume idempotency uses `Idempotency-Key`, dispatches only on newly accepted resume, rejection terminalizes the run, cancellation closes active checkpoints, and runtime tests cover downstream edited-payload propagation plus last-step terminalization

## Carry-Forward Risks

- Frontend generated type updates must not overwrite unrelated local changes.
- Slice 9.5 must add evidence/export lineage for original reviewed output, current edited output, and resumed checkpoint state.
- Frontend slices must use generated API types for review checkpoint read/edit/approve/reject/resume rather than manual duplicate types.

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
- `FlowStepReviewPolicy` is the canonical review-policy contract at API, domain, persistence serialization, published definition, and runtime parser boundaries.
- Review policy cannot be combined with `FlowOutputMode` values classified by `flow_output_mode_has_outbound_delivery`.
- `FlowRunRepository.open_review_checkpoint_for_completed_step` owns the SQL transition and audit outbox insert; the caller owns published-graph interpretation and downstream `next_step_ids` selection.
- Executor pause/yield keeps successful step persistence and review checkpoint opening as separate commits; stale-running reconciliation remains the repair owner for crashes between those commits.
