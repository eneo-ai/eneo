# Retrospective 1 — Flow Run Lifecycle Event Contract

## TL;DR

1. Slice 10.1 added a stable Flow run lifecycle log-event contract.
2. `FlowRunTerminalizer` remains the canonical owner for terminal transitions and audit outbox writes.
3. Lifecycle events are best-effort structured logs, not durable audit or recovery state.
4. Success events are emitted only after audit outbox insertion succeeds.
5. Local validation passed; Docker validation remains blocked by the active Codex process policy.

## Outcome

Implemented `backend/src/intric/flows/application/flow_run_lifecycle_events.py` with one typed event payload and one emit function for terminalization outcomes:

- `transitioned`
- `noop_already_terminal`
- `noop_lost_race`

Integrated the emitter into `backend/src/intric/flows/application/flow_run_terminalization.py` without moving terminalization ownership or changing transaction semantics.

## What Stayed Clean

| Area | Result |
|---|---|
| Canonical owner | `FlowRunTerminalizer` still owns status changes, runtime row closure, checkpoint cancellation, rerun closure, and audit outbox insertion. |
| Audit boundary | `flow_run_audit_outbox` remains the durable lifecycle audit trail. Lifecycle events are operator-facing logs only. |
| Event shape | One `TypedDict`, one schema version constant, one event name constant, one operation constant. |
| PII discipline | The event carries `error_code`, not free-form `error_message`. |
| Tests | Unit tests pin payload shape; integration tests pin success/no-op/rollback behavior with real `logging.LogRecord` payloads. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/test_flow_run_lifecycle_events.py tests/integration/flows/test_flow_terminalization_contract.py -q` | Passed: `8 passed, 16 warnings` |
| `cd backend && uv run pyright ...` for touched source/test files | Passed |
| `cd backend && uv run ruff check ...` for touched source/test files | Passed |
| `cd backend && uv run ruff format --check ...` for touched source/test files | Passed |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for touched source/test/doc paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed |
| `docker exec eneo-41ae93-eneo-1 true` | Blocked before host execution by the active Codex process policy. |

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-plan-20260502T195817Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-lifecycle-operability-implementation-20260502T201432Z.md` | `green`, `GREEN_LIGHT: yes` |

Accepted post-green cleanup:

- Removed the `FlowRunStatus | str` union on `previous_status`.
- Removed the status normalization helper.
- Added unit coverage for both no-op outcomes.
- Documented why free-form failure text is not part of the event payload.

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| Audit outbox delivery/retry/dead-letter state | `flow_run_audit_outbox` delivery model | Slice 10.3 after data-model approval. |
| Metrics backend/dashboard counters | Batch 10 PRD-009 operability | Add after the log-event contract is stable. |
| Runtime health/readiness probe | Flow runtime operability | Slice 10.2 can proceed without migration if it reads existing state only. |
| Integration logging capture workaround | Test infrastructure | Investigate later if more lifecycle log tests appear; do not copy the helper blindly. |
| `tool_calls_metadata` cleanup | Attempt provenance/data model | Requires migration/count proof. |

## Confidence

High. The event/audit ordering is pinned by integration tests, Claude gave green light after implementation review, and local fallback validation passed.
