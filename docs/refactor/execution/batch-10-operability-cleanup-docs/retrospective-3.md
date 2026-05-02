# Retrospective 3 — Flow Audit Outbox Delivery

## TL;DR

1. Slice 10.3 turns durable Flow audit outbox rows into delivered audit logs.
2. Delivery is idempotent because `flow_run_audit_outbox.id` becomes `audit_logs.id`.
3. `FlowRunAuditOutboxRepository` now owns outbox persistence and delivery state.
4. Health and runbook coverage make backlog and dead letters visible without exposing tenant or run identifiers.
5. Claude final verification returned `GREEN_LIGHT: yes` with minimum score `9`, and local validation passed.

## Outcome

Implemented audit outbox delivery with:

- delivery state columns, constraints, and indexes on `flow_run_audit_outbox`
- `FlowRunAuditOutboxRepository` as the canonical outbox persistence owner
- `FlowRunAuditOutboxDeliveryService` for projection, retry, and dead-letter behavior
- `AuditLogRepository.create_if_absent` using PostgreSQL `ON CONFLICT DO NOTHING`
- Celery route and beat schedule for `flows.deliver_audit_outbox`
- Flow runtime health flags for aged backlog and dead letters
- runbook guidance for backlog/dead-letter diagnosis
- unit and integration tests for projection, idempotency, mixed batches, retry/dead-letter behavior, constraints, Celery schedule, health, and terminalization rollback

## What Stayed Clean

| Area | Result |
|---|---|
| Canonical owner | Outbox insert and delivery state moved into `FlowRunAuditOutboxRepository`; `FlowRunRepository` delegates. |
| Idempotency | One idempotency key: `flow_run_audit_outbox.id == audit_logs.id`. |
| Transaction behavior | Delivery uses one outer transaction for `FOR UPDATE SKIP LOCKED` locks and per-row savepoints for isolation. |
| Audit projection | Human audit descriptions are synthesized during delivery; the outbox `action:source` invariant remains metadata. |
| Runtime policy | Retry, batch, interval, and backlog thresholds live in `flow_run_audit_outbox_policy.py`. |
| Terminalizer dependency | `FlowRunTerminalizer` requires explicit outbox repository injection. |
| Operability | Health response is aggregate-only; runbook tells operators not to delete dead-letter rows to silence the probe. |
| Compatibility | No deprecated Flow path, legacy endpoint, or backwards-compatibility branch was preserved. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run ruff check ...` for Slice 10.3 source/tests | Passed |
| `cd backend && uv run ruff format ...` for Slice 10.3 source/tests | Passed |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_audit_outbox_delivery.py tests/unittests/flows/test_flow_review_checkpoint_data_model.py tests/unittests/flows/test_celery_runtime.py tests/unittests/flows/test_flow_runtime_health.py -q` | Passed: `40 passed, 10 warnings` |
| `cd backend && uv run pytest tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/flows/test_flow_terminalization_contract.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_run_repository.py -q` | Passed: `50 passed, 16 warnings` |
| `cd backend && uv run pyright ...` for Slice 10.3 source/tests | Passed: `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for Slice 10.3 touched paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed |

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-20260502T205958Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Plan verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-verification-20260502T210456Z.md` | `green`, `GREEN_LIGHT: yes` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-implementation-verification-20260502T213041Z.md` | `green`, `GREEN_LIGHT: yes` |
| Final verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-final-contract-verification-20260502T214219Z.md` | `green`, `GREEN_LIGHT: yes` |

Accepted plan-review changes:

- human audit descriptions instead of copying `action:source`
- outbox id reused as audit log id
- per-row savepoints
- deterministic validation dead-lettering
- dedicated outbox repository
- central retry/backlog policy
- source-visible rationale for bypassing tenant audit feature flags

Accepted post-green cleanup:

- removed optional terminalizer fallback and required explicit outbox repository injection
- added unit coverage for all Flow audit description mappings
- added unit coverage for failure-message fallback order
- expanded integration constraint coverage to invalid status and negative attempts

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| Dead-letter replay tooling | Flow operability | Add only with an operator audit contract and explicit replay semantics. |
| Runtime-tunable retry backoff | Flow runtime policy | Consider settings-driven backoff if operations need live tuning. |
| Outbox retention cleanup | Batch 10 deferred slice | Revisit in Slice 10.5 so delivered/dead-lettered rows do not grow forever. |
| Batch 11 Flow AI Builder reliability | Batch 11 | Read the Batch 11 plan after Batch 10 completes and improve ownership boundaries where the plan underspecifies reliability. |

## Confidence

High. The implementation passed focused unit and integration validation, pyright, ruff, import-boundary checks, diff whitespace checks, anti-slippage checks, and final Claude green-light verification.
