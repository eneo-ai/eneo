# Batch 8 — Step Rerun Journal

## Status
IN_PROGRESS

## Iteration Log

### Iteration 1 — Plan

- Plan: `docs/refactor/execution/batch-8-step-rerun/plan.md`
- Validation: not run yet
- Retrospective: not run yet
- Claude review: changes required, artifact `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-plan-20260502T093512Z.md`
- Reconciliation: `docs/refactor/execution/batch-8-step-rerun/claude-reconciliation-1.md`
- Outcome: plan revised for Iteration 2 verification

### Iteration 2 — Plan Revision

- Plan: `docs/refactor/execution/batch-8-step-rerun/plan.md`
- Validation: not run yet
- Retrospective: not run yet
- Claude review: green, artifact `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-plan-verification-20260502T094549Z.md`
- Reconciliation: `docs/refactor/execution/batch-8-step-rerun/claude-reconciliation-2.md`
- Outcome: plan accepted for implementation after clarification updates

### Slice 8.1 — Rerun Graph

- Source: `backend/src/intric/flows/flow_run_rerun_graph.py`
- Tests:
  - `backend/tests/unittests/flows/test_flow_rerun_graph.py`
  - `backend/tests/unittests/flows/test_flow_rerun_architecture.py`
- Local validation:
  - `uv run pytest tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py -q` — passed, 19 tests
  - `uv run ruff check src/intric/flows/enums.py src/intric/flows/flow_run_rerun_graph.py tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py` — passed
  - `uv run pyright src/intric/flows/flow_run_rerun_graph.py tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py` — passed
- Docker validation: not run because this Codex process still blocks Docker before execution
- Claude review: green after fix, artifacts:
  - changes required: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-graph-implementation-20260502T100344Z.md`
  - green verification: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-graph-green-format-20260502T100812Z.md`
- Reconciliation: `docs/refactor/execution/batch-8-step-rerun/claude-reconciliation-3.md`
- Outcome: graph foundation green; commit pending sandbox blocker resolution
- Commit attempt: blocked before Git execution with `Rejected("approval required by policy, but AskForApproval is set to Never")`

### Slice 8.2 — Rerun Data Model

- Source:
  - `backend/src/intric/database/tables/flow_tables.py`
  - `backend/src/intric/flows/domain/flow.py`
  - `backend/src/intric/flows/enums.py`
  - `backend/alembic/versions/20260502_flow_run_rerun_operations.py`
- Tests:
  - `backend/tests/unittests/flows/test_flow_rerun_data_model.py`
- Local validation:
  - `uv run pytest tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_rerun_data_model.py -q` — passed, 25 tests
  - `uv run ruff check src/intric/flows/enums.py src/intric/flows/domain/flow.py src/intric/database/tables/flow_tables.py tests/unittests/flows/test_flow_rerun_data_model.py alembic/versions/20260502_flow_run_rerun_operations.py` — passed
  - `uv run pyright src/intric/flows/enums.py src/intric/flows/domain/flow.py src/intric/database/tables/flow_tables.py tests/unittests/flows/test_flow_rerun_data_model.py` — passed
  - `uv run python -m py_compile alembic/versions/20260502_flow_run_rerun_operations.py` — passed
  - `rg -o 'fk_[A-Za-z0-9_]+' alembic/versions/20260502_flow_run_rerun_operations.py | sort -u | awk '{ print length($0), $0 }' | sort -nr` — passed, longest FK name is 46 characters
- Docker validation: blocked before execution when running `docker exec -w /workspace/backend eneo-41ae93-eneo-1 uv run alembic current` with `Rejected("approval required by policy, but AskForApproval is set to Never")`
- Claude review: green after fix, artifacts:
  - changes required: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-data-model-implementation-20260502T102226Z.md`
  - green verification: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-data-model-verification-20260502T102903Z.md`
- Reconciliation: `docs/refactor/execution/batch-8-step-rerun/claude-reconciliation-4.md`
- Outcome: data-model foundation green; commit pending sandbox blocker resolution
- Commit attempt: blocked before Git execution with `Rejected("approval required by policy, but AskForApproval is set to Never")`

### Slice 8.3 — Rerun Request Fingerprint

- Source:
  - `backend/src/intric/flows/flow_run_rerun_request.py`
- Tests:
  - `backend/tests/unittests/flows/test_flow_run_rerun_request.py`
- Local validation:
  - `uv run ruff format src/intric/flows/flow_run_rerun_request.py tests/unittests/flows/test_flow_run_rerun_request.py` — passed, no changes
  - `uv run pytest tests/unittests/flows/test_flow_run_rerun_request.py -q` — passed, 14 tests
  - `uv run pytest tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_rerun_data_model.py tests/unittests/flows/test_flow_run_rerun_request.py -q` — passed, 39 tests
  - `uv run ruff check src/intric/flows/enums.py src/intric/flows/domain/flow.py src/intric/database/tables/flow_tables.py src/intric/flows/flow_run_rerun_graph.py src/intric/flows/flow_run_rerun_request.py tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_rerun_data_model.py tests/unittests/flows/test_flow_run_rerun_request.py alembic/versions/20260502_flow_run_rerun_operations.py` — passed
  - `uv run pyright src/intric/flows/enums.py src/intric/flows/domain/flow.py src/intric/database/tables/flow_tables.py src/intric/flows/flow_run_rerun_graph.py src/intric/flows/flow_run_rerun_request.py tests/unittests/flows/test_flow_rerun_graph.py tests/unittests/flows/test_flow_rerun_architecture.py tests/unittests/flows/test_flow_rerun_data_model.py tests/unittests/flows/test_flow_run_rerun_request.py` — passed
- Docker validation: not run because this Codex process still blocks Docker before execution
- Claude review: green, artifact `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-request-fingerprint-20260502T103753Z.md`
- Outcome: request fingerprint foundation green; commit pending sandbox blocker resolution

## Repository Gate

- Branch: `feature/refactor-flows-flowai`
- HEAD: `7e998609 flows: align evidence artifacts with result files`
- Staged files: Batch 8 rerun graph, data model, request fingerprint, and execution docs pending commit
- Known do-not-stage local files:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
  - `docs/refactor/goals.md`

## Docker Status

`docker ps --format '{{.Names}}' | sort` was attempted in this refreshed session and was still blocked before Docker execution:

```text
Rejected("approval required by policy, but AskForApproval is set to Never")
```

The Batch 8 plan keeps Docker as the canonical validation mode from `docs/refactor/implementation-order.md`. If this process keeps blocking Docker, implementation validation will use the local fallback commands listed in the plan and record that choice here.

## Inputs Read

- `docs/refactor/phase4/refactor-plan.md`
- `docs/refactor/implementation-order.md`
- `docs/refactor/phase0/baseline.md`
- `docs/refactor/phase7/implementation-readiness.md`
- `docs/refactor/execution/implementation-bootstrap.md`
- `docs/refactor/execution/loop-protocol.md`
- `docs/refactor/execution/retrospective-checklist.md`
- `docs/refactor/prd/PRD-003-runtime-reliability-and-feature-gaps.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/comment-and-readability-standard.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`
- `docs/engineering/frontend-state-standard.md`

## Initial Code Inventory

| Area | Evidence | Decision |
|---|---|---|
| Redispatch | `backend/src/intric/flows/api/flow_run_execution_router.py:376-455`, `backend/src/intric/flows/application/flow_run_service.py:690-757` | Rerun must be separate from stale queued redispatch. |
| Permission action | `backend/src/intric/flows/flow_access_policy.py:34-36`, `backend/src/intric/flows/flow_access_policy.py:167-172` | Enable only through an explicit Batch 8 permission decision; do not let `FLOWS_RUN` imply rerun. |
| Current result projection | `backend/src/intric/database/tables/flow_tables.py:455-532` | Clearing stale current outputs requires attempt snapshots first. |
| Attempts | `backend/src/intric/database/tables/flow_tables.py:535-606`, `backend/src/intric/flows/domain/flow.py:177-202` | Attempts are the right historical lineage owner but need rerun/snapshot columns. |
| Attempt numbering | `backend/src/intric/flows/runtime/executor.py:524-535` | Replace Celery retry-count attempt numbering with persisted allocation. |
| Step file rows | `backend/src/intric/database/tables/flow_tables.py:609-756` | Reuse for rerun attempt-scoped inputs/artifacts. |
| Published definition | `backend/src/intric/flows/published_definition.py:66-129` | Use run version snapshot as DAG source. |
| Live step dependency table | `backend/src/intric/database/tables/flow_tables.py:193-235` | Do not use live authoring dependencies for historical rerun until version-scoped. |
| Evidence export | `backend/src/intric/flows/flow_run_evidence_bundle.py:96-117`, `backend/src/intric/flows/flow_run_export_json.py:85-149` | Add rerun lineage to hashed evidence payload. |
| Template-derived dependencies | `backend/src/intric/flows/runtime/step_input_resolution.py:163-201`, `backend/src/intric/flows/runtime/http_orchestration.py:129-155`, `backend/src/intric/flows/runtime/http_orchestration.py:296-328`, `backend/src/intric/flows/runtime/template_fill_runtime.py:402-431`, `backend/src/intric/flows/runtime/step_execution_runtime.py:666-675` | Rerun DAG must scan runtime-interpolated fields, not only `input_source`. |
| Run revision token | `backend/src/intric/database/tables/base_class.py:35-39` | `updated_at` is display metadata; add `FlowRuns.revision` for compare-and-swap. |
| Current result files | `backend/src/intric/database/tables/flow_tables.py:526-528`, `backend/src/intric/database/tables/flow_tables.py:695-697` | Add `FlowStepResults.current_attempt_no` so old attempt files do not render as current. |
| Rerun audit owner | `backend/src/intric/database/tables/flow_tables.py:759-821`, `backend/src/intric/database/tables/flow_tables.py:795` | Keep terminal outbox one row per run; make rerun operation rows the rerun audit fact. |
| Dispatch-after-commit helper | `backend/src/intric/flows/api/flow_run_execution_router.py:212-216`, `backend/src/intric/flows/application/flow_dispatch.py:47-66` | Do not use the current create-run helper for recoverable rerun dispatch unless it is generalized with explicit behavior. |

## Decisions Made During Planning

- `flow_run_rerun_operations` is the durable rerun request and audit owner.
- `flow_run_rerun_invalidated_steps` makes root/downstream invalidation explicit instead of hiding it in status updates.
- Attempt output/input snapshots are required before current result rows can be reset.
- Rerun DAG uses published definition snapshot semantics plus static template-reference scanning, not live `FlowStepDependencies`.
- The public rerun request uses `expected_run_revision` backed by `FlowRuns.revision`.
- `FLOWS_MANAGE` is the current explicit rerun equivalent; `FLOWS_RUN` and original run ownership are insufficient.
- Service-key rerun remains denied in Batch 8.
- Deterministic `request_fingerprint` is the rerun idempotency key; no client-supplied rerun idempotency key is added.
- The operation row owns root attempt number allocation through `root_attempt_no`; executor does not recompute it.
- `FlowStepResults.current_attempt_no` separates current artifact display from historical attempt file evidence.
- Active rerun operations become terminal when run terminalization happens: `cancelled` for cancelled runs, otherwise `failed` with `failure_code = "run_terminalized"`.
- `flow_run_rerun_conflict` is not a Batch 8 public error code; deterministic replay and stale revision cover the concurrency outcomes.
- `dependency_sources_json` is evidence-only and must be emitted from pinned `RerunDependencyKind` values.
- The rerun dispatch path must leave queued rerun state recoverable if dispatch fails after commit.

## Carry-Forward Risks

- The plan intentionally defers Batch 9 review acceptance criteria. Retrospective must mark those items `n/a` or carry-forward, not silently claim Batch 9 work.
- Docker is still blocked in this running Codex process, despite the user-level config update.
