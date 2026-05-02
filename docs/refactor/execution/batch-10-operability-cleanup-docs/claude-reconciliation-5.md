# Claude Reconciliation 5 — Delivered Audit Outbox Retention

## TL;DR

1. Claude rejected the initial created-at cutoff plan because it would duplicate audit retention semantics.
2. The implemented cleanup deletes delivered Flow audit outbox rows only after the matching `audit_logs.id` row is gone.
3. Pending and dead-lettered outbox rows stay visible because they still represent delivery work or unresolved audit incidents.
4. Worker reporting now includes delivered outbox cleanup without mixing it into Flow runtime debug/artifact tombstoning.
5. Claude final verification returned `GREEN_LIGHT: yes` with minimum score `9`.

## Claude Artifacts

| Pass | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-plan-20260502T222409Z.md` | `changes_required`, `GREEN_LIGHT: no`, minimum score `6` |
| Plan verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-plan-verification-20260502T222823Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `8` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-implementation-verification-20260502T224452Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `9` |
| Strict final verification | `.codex/artifacts/claude-peer-loop-batch-10-flow-audit-outbox-retention-docs-final-green-20260502T224714Z.md` | `green`, `GREEN_LIGHT: yes`, minimum score `9` |

## Accepted Findings

| Finding | Decision | Source impact |
|---|---|---|
| Mirroring audit retention with `FlowRunAuditOutbox.created_at` and tenant retention days would create a second retention owner. | Use an anti-join against `audit_logs.id`; delivered outbox rows are eligible only after the audit log twin is deleted. | `data_retention_service.py`. |
| Flow runtime debug/artifact tombstoning and audit-outbox mirror cleanup are different responsibilities. | Keep `FlowRuntimeCleanupCounts` unchanged and add a sibling `delete_old_delivered_flow_audit_outbox_rows() -> int`. | `data_retention_service.py`, `data_retention_worker.py`. |
| Pending and dead-lettered rows must not be deleted as volume cleanup. | Delete only `delivery_status='delivered'`; preserve pending delivery work and unresolved dead letters. | `data_retention_service.py`, `test_flow_runtime_retention_cleanup.py`. |
| Shared audit retention should not import Flow infrastructure. | Run the cleanup from the data retention worker after Flow runtime cleanup in its own transaction. | `data_retention_worker.py`. |
| Runbook health docs omitted existing audit outbox fields and flags. | Document the `audit_outbox` health fields, delivery backlog flag, dead-letter flag, and retention policy. | `docs/runbooks/flows.md`. |
| Current architecture docs still described deleted result-level tool-call metadata. | Remove those references and point tool-call evidence to attempt provenance. | `docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md`. |

## Optional Claude Notes Accepted

| Note | Decision |
|---|---|
| The worker's local `delete_outbox_rows` rebind was only a line-length workaround. | Inline the method call for consistency with the sibling retention blocks. |
| The worker test's `transaction_count == 5` assertion was meaningful but unnamed. | Use `expected_independent_cleanup_transactions` to name the invariant. |

## Rejected Or Deferred

| Suggestion | Decision | Reason |
|---|---|---|
| Add a delivered-row partial index immediately. | Deferred. | The anti-join is correct without a new index. Measure representative delivered-row volume before adding schema weight. |
| Delete or age out dead-lettered rows in this cleanup. | Deferred. | Dead letters are unresolved audit incidents. They need replay or acknowledgement semantics before retention can remove them. |
| Move cleanup into shared audit retention. | Rejected. | That would invert the dependency boundary by making audit retention depend on Flow infrastructure. |

## Verification Questions

| Question | Answer |
|---|---|
| Is audit retention still the single source of truth? | Yes. The cleanup uses `NOT EXISTS audit_logs.id = flow_run_audit_outbox.id`; no tenant retention cutoff appears on the outbox cleanup path. |
| Are pending and dead-lettered rows preserved? | Yes. Integration tests assert pending and dead-lettered rows remain after cleanup. |
| Does batching use one source of truth? | Yes. The cleanup reuses `RETENTION_BATCH_SIZE` and loops until `rowcount == 0`. |
| Does the worker expose the new count and total? | Yes. `DeletedCounts`, result initialization, total calculation, and success logging include `flow_audit_outbox_delivered_rows`. |
| Are docs aligned with the current contract? | Yes. The runbook lists audit outbox health fields and flags, and the architecture map no longer documents result-level `tool_calls_metadata`. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run ruff check ...` for Slice 10.5 source/tests | Passed |
| `cd backend && uv run ruff format --check ...` for Slice 10.5 source/tests | Passed: `4 files already formatted` |
| `cd backend && uv run pyright ...` for Slice 10.5 source/tests | Passed: `0 errors, 0 warnings, 0 informations` |
| `cd backend && uv run pytest tests/unittests/data_retention/test_data_retention_worker.py tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_audit_outbox_delivery.py tests/unittests/flows/test_flow_runtime_health.py -q` | Passed: `28 passed, 16 warnings` |
| `cd backend && uv run lint-imports --no-cache` | Passed: `3 kept, 0 broken` |
| `git diff --check -- ...` for Slice 10.5 paths | Passed |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean` |
| `rg -n "created_at.*retention\|retention_days.*FlowRunAuditOutbox\|FlowRunAuditOutbox.*retention_days\|AuditRetentionPolicy.*FlowRunAuditOutbox" backend/src/intric/data_retention backend/src/intric/flows backend/tests` | Passed: no output |
| `rg -n "tool_calls_metadata\|flow_step_results\\.tool_calls" docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md` | Passed: no output |

## Confidence

High. The slice removes an audit-retention bypass without adding a second retention policy, keeps delivery incidents visible, adds behavior-focused tests, and leaves no deprecated Flow compatibility path behind.
