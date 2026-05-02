# Claude Reconciliation 3 — Flow Audit Outbox Delivery

## TL;DR

1. Claude rejected the first Slice 10.3 plan because the outbox rows were durable but not yet deliverable, idempotent, or operator-visible.
2. The accepted design reuses `flow_run_audit_outbox.id` as the delivered `audit_logs.id`.
3. `FlowRunAuditOutboxRepository` is the canonical owner for outbox inserts and delivery state; `FlowRunRepository` no longer owns outbox-specific insert methods.
4. Delivery projects rows into human audit logs, retries transient failures, and dead-letters deterministic invalid rows without blocking neighboring rows.
5. Final verification returned `GREEN_LIGHT: yes` with minimum score `9`.

## Claude Artifacts

| Pass | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-20260502T205958Z.md` | `changes_required`, `GREEN_LIGHT: no`, minimum score `5` |
| Plan verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-plan-verification-20260502T210456Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `8` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-implementation-verification-20260502T213041Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `8` |
| Final verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-delivery-final-contract-verification-20260502T214219Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `9` |

## Accepted Findings

| Finding | Decision | Source impact |
|---|---|---|
| Copying `action:source` into `audit_logs.description` would make audit logs less readable. | Keep the outbox description as an invariant and synthesize human audit descriptions during delivery. | `flow_run_audit_outbox_delivery.py` owns projection. |
| Delivery idempotency needed one durable key. | Reuse `flow_run_audit_outbox.id` as `audit_logs.id`; insert with `ON CONFLICT DO NOTHING`. | `flow_tables.py`, `audit_log_repo_impl.py`, delivery tests. |
| A bad row should not roll back neighboring deliveries. | Process each row inside a nested transaction while the batch holds `FOR UPDATE SKIP LOCKED` locks. | `flow_run_audit_outbox_repo.py`, `flow_run_audit_outbox_delivery.py`. |
| Deterministic audit-domain validation should not consume retry slots. | Treat projection/domain `ValueError` as immediate dead-letter. | Delivery service and mixed-batch integration test. |
| Outbox ownership was drifting into `FlowRunRepository`. | Add `FlowRunAuditOutboxRepository` as the canonical outbox persistence owner. | `flow_run_repo.py` delegates instead of owning outbox insert SQL. |
| Retry and health thresholds should have one owner. | Add `flow_run_audit_outbox_policy.py`. | Celery beat, delivery service, and health probe share constants. |
| The terminalizer fallback dependency was dead production code. | Require explicit `FlowRunAuditOutboxRepository` in `FlowRunTerminalizer`. | `flow_run_terminalization.py`, `flow_run_service.py`, `executor.py`, container/tests. |

## Rejected Or Deferred

| Suggestion | Decision | Reason |
|---|---|---|
| Add an admin replay tool for dead-letter rows in this slice. | Deferred. | The runbook documents manual diagnosis; replay deserves its own operator/audit contract. |
| Move retry backoff into runtime settings now. | Deferred. | Current Flow runtime policy constants are code-owned; settings-driven tuning can happen when operations need live tuning. |
| Generalize outbox projection into a protocol. | Rejected for now. | There is one concrete outbox projection owner; a generic abstraction would be speculative. |

## Verification Questions

| Question | Answer |
|---|---|
| Are outbox ids generated safely? | Yes. `FlowRunAuditOutbox` inherits `BasePublic`, and `BasePublic` inherits `IdMixin` with `server_default=func.gen_random_uuid()`. |
| Is the Celery delivery transaction shape acceptable? | Yes. `enable_autobegin_for_flow_task_session(session)` is inert inside the explicit `session.begin()` block, while the explicit block owns the `FOR UPDATE SKIP LOCKED` lock lifetime. |
| Were database constraints exercised against PostgreSQL? | Yes. The integration tests used testcontainers with `pgvector/pgvector:pg16`. |
| Does the health response leak tenant/run identifiers? | No. The outbox health summary is aggregate-only. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run ruff check ...` for Slice 10.3 touched source/tests | Passed |
| `cd backend && uv run ruff format ...` for Slice 10.3 touched source/tests | Passed |
| `cd backend && uv run pytest tests/unittests/flows/test_flow_audit_outbox_delivery.py tests/unittests/flows/test_flow_review_checkpoint_data_model.py tests/unittests/flows/test_celery_runtime.py tests/unittests/flows/test_flow_runtime_health.py -q` | Passed: `40 passed, 10 warnings` |
| `cd backend && uv run pytest tests/integration/flows/test_flow_audit_outbox_delivery.py tests/integration/flows/test_flow_runtime_health.py tests/integration/flows/test_flow_terminalization_contract.py tests/integration/flows/test_flow_run_review_checkpoint_repository.py tests/integration/flows/test_flow_run_repository.py -q` | Passed: `50 passed, 16 warnings` |
| `cd backend && uv run pyright ...` for Slice 10.3 touched source/tests | Passed: `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for Slice 10.3 touched paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed |

## Confidence

High. The accepted findings directly shaped the implementation, final verification returned green, and the remaining deferred items are explicit operator follow-ups rather than hidden compatibility paths.
