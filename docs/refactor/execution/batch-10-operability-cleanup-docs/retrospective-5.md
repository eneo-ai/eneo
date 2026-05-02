# Retrospective 5 — Delivered Audit Outbox Retention

## TL;DR

1. Slice 10.5 makes delivered Flow audit outbox cleanup follow actual audit-log deletion.
2. `audit_logs` remains the canonical delivered audit record; the outbox is delivery staging state.
3. Pending and dead-lettered rows remain because they are operational work, not retention waste.
4. Runbook and architecture docs now match the current audit outbox and tool-call evidence contracts.
5. Claude final verification returned `GREEN_LIGHT: yes` with minimum score `9`, and focused validation passed.

## Outcome

Implemented the cleanup with:

- `DataRetentionService.delete_old_delivered_flow_audit_outbox_rows() -> int`
- anti-join eligibility: delivered outbox row exists and matching `audit_logs.id` no longer exists
- `RETENTION_BATCH_SIZE` reuse and looped batched delete
- separate worker transaction after Flow runtime debug/artifact cleanup
- `flow_audit_outbox_delivered_rows` count in worker results, total, and success log
- integration tests for the delivered/pending/dead-lettered state matrix
- worker unit test for count, total, and transaction separation
- runbook coverage for audit outbox health fields, flags, and retention policy
- architecture-map cleanup for deleted result-level `tool_calls_metadata`

## What Stayed Clean

| Area | Result |
|---|---|
| Canonical owner | `audit_logs` owns delivered audit lifetime. Delivered outbox rows are removed only after the audit log twin is gone. |
| Delivery state | `flow_run_audit_outbox` remains the staging table for pending delivery and unresolved dead letters. |
| Retention policy | No outbox-specific retention cutoff or tenant retention mirror was added. |
| Runtime cleanup counts | `FlowRuntimeCleanupCounts` remains scoped to Flow debug evidence and generated artifact cleanup. |
| Worker failure isolation | Outbox cleanup runs in its own transaction; failures are reported separately. |
| Tests | Behavior tests cover preservation, deletion, idempotency, batching, worker count, total, and transaction count. |
| Comments | The new implementation comment explains the audit ownership invariant rather than narrating SQL. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run ruff check src/intric/data_retention/infrastructure/data_retention_service.py src/intric/data_retention/infrastructure/data_retention_worker.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/data_retention/test_data_retention_worker.py` | Passed |
| `cd backend && uv run ruff format --check src/intric/data_retention/infrastructure/data_retention_service.py src/intric/data_retention/infrastructure/data_retention_worker.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/data_retention/test_data_retention_worker.py` | Passed: `4 files already formatted` |
| `cd backend && uv run pyright src/intric/data_retention/infrastructure/data_retention_service.py src/intric/data_retention/infrastructure/data_retention_worker.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/data_retention/test_data_retention_worker.py` | Passed: `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run pytest tests/unittests/data_retention/test_data_retention_worker.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_audit_outbox_delivery.py tests/unittests/flows/test_flow_runtime_health.py -q` | Passed: `28 passed, 16 warnings` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for Slice 10.5 paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean` |
| `rg -n "created_at.*retention\|retention_days.*FlowRunAuditOutbox\|FlowRunAuditOutbox.*retention_days\|AuditRetentionPolicy.*FlowRunAuditOutbox" backend/src/intric/data_retention backend/src/intric/flows backend/tests` | Passed: no output |
| `rg -n "tool_calls_metadata\|flow_step_results\\.tool_calls" docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md` | Passed: no output |

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-plan-20260502T222409Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Plan verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-plan-verification-20260502T222823Z.md` | `green`, `GREEN_LIGHT: yes` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-implementation-verification-20260502T224452Z.md` | `green`, `GREEN_LIGHT: yes` |
| Strict final verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-final-green-20260502T224714Z.md` | `green`, `GREEN_LIGHT: yes` |

Accepted cleanup:

- changed the plan from a created-at retention cutoff to audit-log anti-join semantics
- kept audit retention independent from Flow infrastructure
- kept delivered outbox cleanup out of `FlowRuntimeCleanupCounts`
- preserved pending and dead-lettered rows
- inlined the worker method call after Claude flagged the local rebind
- named the worker test transaction-count expectation

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| Delivered-row partial index | Flow data model | Measure representative delivered-row cleanup volume before adding an index. |
| Dead-letter replay or acknowledgement | Flow operability | Define a reviewed contract before any retention cleanup can remove dead-lettered rows. |
| Flow import forwarding modules | Batch 10.6 | Decide whether to delete, rename, or explicitly document the canonical import path without preserving never-shipped compatibility. |
| Batch 11 Flow AI Builder reliability | Batch 11 | Read the Batch 11 plan after Batch 10 completes and improve reliability ownership where the plan underspecifies runtime failure modes. |

## Confidence

High. The cleanup follows the single-source-of-truth audit lifetime, has direct tests for the important row states, and leaves pending/dead-lettered operational evidence intact for human operators.
