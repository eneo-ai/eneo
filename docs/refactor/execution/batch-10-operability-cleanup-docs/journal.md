# Batch 10 — Operability, Cleanup, And Docs Journal

## Status

IN PROGRESS

## Starting Point

- Branch: `feature/refactor-flows-flowai`
- HEAD: `02292fe3 flows: add review checkpoint frontend state`
- Previous completed batch: Batch 9 Human Review Pause/Edit/Resume
- Staged files at start: none
- Known unrelated dirty files:
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- Additional untracked local scratch:
  - `docs/refactor/goals.md`
- Batch 10 directory: `docs/refactor/execution/batch-10-operability-cleanup-docs/`
- Docker status: `docker exec eneo-41ae93-eneo-1 true` is blocked by Codex process policy before host execution with `approval required by policy, but AskForApproval is set to Never`; local validation fallback is required.

## Iteration Log

### Iteration 1 — Plan Draft

- Plan: `docs/refactor/execution/batch-10-operability-cleanup-docs/plan.md`
- Chosen first slice: Flow lifecycle operability event contract.
- Rationale: current audit outbox delivery/dead-letter state is absent from the table shape and needs a data-model approval gate; lifecycle events are implementation work that improves operability without adding migrations or a second terminalization owner.
- Validation: not run yet.
- Claude review: `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-plan-20260502T195817Z.md`
- Claude verdict: `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

### Iteration 1 Reconciliation

Accepted findings:

| Claude finding | Decision |
|---|---|
| `flow_run_operability.py` is too generic. | Rename the proposed owner to `backend/src/intric/flows/application/flow_run_lifecycle_events.py`. |
| Three emit functions and an optional dataclass shape are shallow. | Use one `TypedDict` plus one `emit_flow_run_terminalization_event(...)` function with a typed `outcome`. |
| Module placement at `flows/` root is ambiguous. | Place the event contract under `flows/application/` because the first caller is the application terminalizer. |
| Event/audit boundary was not explicit enough. | The module contract must state lifecycle events are best-effort observability, not audit durability; `flow_run_audit_outbox` remains canonical. |
| `trace_id` source was undeclared. | Use persisted `FlowRun.trace_id`, already present on `FlowRun`. |
| Audit outbox delivery was understated. | `rg "FlowRunAuditOutbox" backend/src` shows only the table and repo inserts; Slice 10.3 is a delivery-model and worker decision, not just a migration. |
| 10.1 does not close metrics. | Plan now states 10.1 only closes the structured event/log half; metrics remain later Batch 10 work. |
| Test mechanism was not pinned. | Use `caplog.records` filtered by `record.event == "flow_run.lifecycle"`; no fake recorder or interface. |
| Bespoke anti-slippage regex was noisy. | Use existing `./scripts/gate-local/anti_slippage.sh --worktree`. |

## Carry-Forward From Prior Batches

| Risk | Source | Batch 10 handling |
|---|---|---|
| Flow audit outbox has durable insert semantics but no consumer, delivery/retry state, or dead-letter state. | `FlowRunAuditOutbox` table has lifecycle/audit columns but no delivery columns; `rg "FlowRunAuditOutbox" backend/src` finds only the table and inserts. | Defer to a delivery-model/data-model-approved slice after lifecycle event contract. |
| `tool_calls_metadata` remains on result rows after attempt provenance became canonical. | Batch 7A carry-forward and current source reads/writes. | Defer to a migration/count-proof cleanup slice. |
| Broad frontend app check has unrelated baseline failures. | Batch 9 reconciliation. | Do not touch frontend in Slice 10.1. |

### Iteration 2 — Slice 10.1 Implementation

Changed files:

- `backend/src/intric/flows/application/flow_run_lifecycle_events.py`
- `backend/src/intric/flows/application/flow_run_terminalization.py`
- `backend/tests/unittests/flows/test_flow_run_lifecycle_events.py`
- `backend/tests/integration/flows/test_flow_terminalization_contract.py`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/plan.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/journal.md`
- `docs/refactor/execution/batch-10-operability-cleanup-docs/claude-reconciliation-1.md`

Implementation summary:

- Added one narrow lifecycle event module under `flows/application`.
- Kept `FlowRunTerminalizer` as the canonical owner for terminal state and audit outbox insertion.
- Emitted `transitioned` only after `insert_terminal_audit_outbox` returns an id.
- Emitted `noop_already_terminal` for duplicate terminalization and `noop_lost_race` for failed CAS/no-update outcomes.
- Kept invariant failure and audit-outbox insert failure paths free of misleading success events.
- Used `FlowRun.trace_id` from the persisted run; no request-context plumbing.
- Kept the event contract as structured logging only; durable recovery/audit remains `flow_run_audit_outbox`.

Validation:

| Command | Result |
|---|---|
| `cd backend && uv run ruff check src/intric/flows/application/flow_run_lifecycle_events.py src/intric/flows/application/flow_run_terminalization.py tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py` | Passed |
| `cd backend && uv run ruff format --check src/intric/flows/application/flow_run_lifecycle_events.py src/intric/flows/application/flow_run_terminalization.py tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py` | Passed |
| `cd backend && uv run pyright src/intric/flows/application/flow_run_lifecycle_events.py src/intric/flows/application/flow_run_terminalization.py tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py` | Passed |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py -q` | Passed: `8 passed, 16 warnings` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for touched source/test/doc paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean` |
| `docker exec eneo-41ae93-eneo-1 true` | Blocked by current Codex process policy before host execution: `approval required by policy, but AskForApproval is set to Never` |

Notes:

- The first targeted test run failed because the integration logging setup bypassed pytest root capture for the lifecycle logger. The final tests still assert real `logging.LogRecord` payloads through `caplog.records`; the test helper attaches pytest's capture handler directly to the lifecycle logger for the action window and restores the logger afterward.
- `docker exec` remains unavailable in this Codex process despite normal command usage and no escalation request. Local fallback validation completed.

### Iteration 2 Claude Verification

- Claude artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-implementation-20260502T201432Z.md`
- Claude verdict: `green`
- Claude green light: `yes`
- Claude minimum score: `8`

Accepted non-blocking cleanup from Claude before commit:

- Tightened `previous_status` from `FlowRunStatus | str` to `FlowRunStatus`.
- Removed the status normalization helper.
- Added a module-docstring rationale for excluding free-form failure text from the lifecycle event.
- Added unit pins for `noop_already_terminal` and `noop_lost_race` payloads.

Verification answers:

| Question | Answer |
|---|---|
| Is `FlowRun.trace_id` non-null at domain and DB levels? | Yes. `FlowRun.trace_id` is required on the domain model and `FlowRuns.trace_id` is `nullable=False` with a default. |
| Does `flow_run_lifecycle_events.py` have only one source importer? | Yes. `rg "flow_run_lifecycle_events\\|emit_flow_run_terminalization_event" backend/src backend/tests` shows the only source importer is `flow_run_terminalization.py`; other references are tests. |
| Is the module earned beyond Slice 10.1? | Yes for the current slice because it owns a stable event schema separate from terminalization logic. Revisit in later Batch 10 slices if new lifecycle events need a different module shape. |
| Is `_capture_flow_lifecycle_logs` duplicated elsewhere? | No. Current references are limited to `test_flow_terminalization_contract.py`. |
