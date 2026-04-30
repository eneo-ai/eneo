# Batch 3 - Claude Plan Reconciliation

Claude plan-review artifact:

- `.codex/artifacts/claude-peer-loop-batch-3-lifecycle-terminalization-audit-plan-20260430T063406Z.md`

## Verdict

- Claude verdict: `changes_required`
- Claude green light: `no`
- Claude minimum score: `6`
- Codex classification: plan findings accepted before implementation

## Accepted Findings And Plan Changes

| Finding | Classification | Codex action |
|---|---|---|
| Terminal call-site inventory missed executor paths for checksum drift, invalid definition, and missing step. | accepted | Added `executor.py:379`, `executor.py:391`, and `executor.py:509` to the retarget list. |
| `_audit_run_terminal_state` was not explicitly removed. | accepted | Plan now deletes `_audit_run_terminal_state` and its completion/failure call sites; terminal outbox replaces ARQ-backed lifecycle audit. |
| Outbox dedupe key was unspecified. | accepted | Plan now uses `UNIQUE (flow_run_id)` for Batch 3 terminal-only audit. |
| `update_status`, `cancel`, `fail_stale_running_run`, and `_mark_run_failed` helpers were hedged instead of deleted. | accepted | Plan now commits to deleting those source-only terminal paths after retargeting. |
| Service and Celery stale-running reconcilers differ today. | accepted | Plan keeps stale-running behavior pins and explicitly targets unified terminalization for both paths. |
| Terminal audit coverage delta was implicit. | accepted | Plan now states current executor-only audit coverage and post-Batch-3 all-terminal-transition outbox coverage. |
| Flat `flow_run_lifecycle.py` owner and "lifecycle projection" wording were weak. | accepted | Plan now uses `backend/src/intric/flows/enums.py` as the status predicate owner and removes "projection" wording. |
| Terminal source should be closed, not a free-form string. | accepted | Plan now requires `FlowRunTerminalSource` enum plus DB CHECK. |
| Completed terminalization should not silently close active step rows. | accepted | Plan now makes active step rows on completed terminalization an invariant error. |
| `metadata_json` and delivery-state columns are premature without a parser/worker. | accepted | Plan removes generic metadata and delivery columns from Batch 3. Batch 10 owns delivery/retry schema. |
| FK delete behavior and Alembic heads command were unspecified. | accepted | Plan now states FK delete behavior and includes `cd backend && uv run alembic heads`. |
| Source guard was incomplete. | accepted | Plan now checks direct terminal writes, audit helper, failure helpers, cancel calls, and raw terminal status strings. |

## Local Verification Of Claude Claims

- `rg -n "update_status\\(|def update_status|\\.update_status\\(" backend/src/intric/flows -g'*.py'`
  found only terminal update callers plus `FlowRunRepository.update_status`.
- `rg -n "_audit_run_terminal_state\\(|def _audit_run_terminal_state|_mark_run_failed\\(|def _mark_run_failed|fail_stale_running_run\\(|def fail_stale_running_run|\\.cancel\\(" backend/src/intric/flows -g'*.py'`
  confirmed the old terminal helpers and audit call sites.
- `rg -n "FlowRunStatus\\.(COMPLETED|FAILED|CANCELLED)|status=FlowRunStatus|status = FlowRunStatus|FlowRunStatus\\(" ...`
  confirmed the missing executor terminal paths.
- `cd backend && uv run alembic heads` returned a single head:
  `20260426_drop_step_mcp_tools (head)`.

## Remaining Plan Risk

The FK delete policy is intentionally stricter than the current
flow-run cascade path. If this blocks existing Flow deletion or retention
behavior during implementation tests, stop and revisit the outbox
durability policy rather than silently changing it.
