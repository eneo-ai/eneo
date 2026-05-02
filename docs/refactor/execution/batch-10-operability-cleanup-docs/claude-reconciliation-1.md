# Claude Reconciliation 1 — Flow Run Lifecycle Events

## TL;DR

1. Claude rejected the first Slice 10.1 plan because the ownership and event shape were still too generic.
2. The accepted owner is `backend/src/intric/flows/application/flow_run_lifecycle_events.py`.
3. `FlowRunTerminalizer` remains the only owner for terminal state transitions and audit outbox insertion.
4. Lifecycle events are structured logs for operators, not durable audit or recovery state.
5. Audit outbox delivery/retry/dead-letter work is deferred because the current source has no consumer.

## Source Review

- Artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-plan-20260502T195817Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `7`

## Accepted Changes

| Claude finding | Local verification | Reconciliation |
|---|---|---|
| `flow_run_operability.py` was too generic. | The first caller is terminalization, not a generic operability service. | Use `backend/src/intric/flows/application/flow_run_lifecycle_events.py`. |
| Multiple emit functions and optional dataclass shape were shallow. | Slice 10.1 only needs terminalization outcomes. | Use one `TypedDict` and one `emit_flow_run_terminalization_event(...)`. |
| Module placement at `flows/` root was ambiguous. | `FlowRunTerminalizer` owns the lifecycle boundary in `backend/src/intric/flows/application/flow_run_terminalization.py`. | Place the event contract in the application package beside the terminalizer. |
| Event/audit boundary was not explicit enough. | `flow_run_audit_outbox` already stores durable lifecycle audit rows. | Module docstring states events are best-effort observability and not audit/recovery state. |
| `trace_id` source was unclear. | `FlowRun.trace_id` exists on the domain model and table. | Use the persisted run trace id; do not add request-context plumbing. |
| Audit outbox delivery was understated. | `rg "FlowRunAuditOutbox" backend/src` finds the table and repository inserts, but no backend consumer. | Defer delivery/retry/dead-letter design to Slice 10.3 with a data-model approval gate. |
| Test mechanism was not pinned. | Event observability should be verified at the logging contract, not through a fake recorder. | Assert `caplog.records` filtered by `record.event == "flow_run.lifecycle"`. |
| Bespoke anti-slippage guard was noisy. | The repository already has `scripts/gate-local/anti_slippage.sh`. | Use `./scripts/gate-local/anti_slippage.sh --worktree`. |

## Rejected Or Deferred

| Suggestion | Decision | Why |
|---|---|---|
| Add audit outbox delivery state in Slice 10.1. | Deferred. | Delivery state changes require schema, worker, retry, and dead-letter ownership decisions. |
| Close metrics in Slice 10.1. | Deferred. | The slice establishes the stable lifecycle event contract first; metrics backend/dashboard work follows. |
| Add a recorder interface for tests. | Rejected. | There is one implementation and no external seam; tests can assert real log records. |

## Acceptance Criteria

- `FlowRunTerminalizer` emits `transitioned`, `noop_already_terminal`, and `noop_lost_race` lifecycle events from the terminalization boundary.
- A `transitioned` event is emitted only after the audit outbox insert succeeds.
- Audit outbox insert failure rolls back terminal state and emits no misleading success event.
- Event fields include tenant, flow, run, trace, source, target status, previous status, revision, audit outbox id, and error code.
- Tests assert behavior through real `logging.LogRecord` payloads.

## Confidence

High. Claude's accepted findings were concrete, locally verified, and incorporated before implementation.

## Verification Pass

- Artifact: `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-implementation-20260502T201432Z.md`
- Verdict: `green`
- Green light: `yes`
- Minimum score: `8`

Non-blocking follow-ups accepted before commit:

- Removed the `FlowRunStatus | str` union on `previous_status`.
- Deleted the status normalization helper made unnecessary by the tighter type.
- Added a rationale for excluding free-form failure text from lifecycle logs.
- Added unit pins for both no-op outcomes.
