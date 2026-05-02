# Batch 9 Claude Reconciliation 2

TL;DR:
1. Claude returned `GREEN_LIGHT: no` for the second Batch 9 plan review.
2. The remaining blockers were concrete plan gaps, not source implementation issues.
3. The plan now separates the lifecycle-source rename from the checkpoint data-model slice.
4. Review checkpoint audit outbox rows now have checkpoint-revision ownership instead of reusing the terminal run-revision key.
5. Resume timing, permissions, output-mode side effects, and downstream edited-output tests are pinned before implementation.

## Review Artifact

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-verification-20260502T153942Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `7` |

## Accepted Findings

| Finding | Local verification | Plan revision |
|---|---|---|
| Review outbox rows cannot reuse the terminal unique key. | `backend/src/intric/database/tables/flow_tables.py:1075-1079` uniquely keys `flow_run_audit_outbox` by `(flow_run_id, run_revision)`, while review edit/approve/reject mutate checkpoint revision. | Added checkpoint outbox columns and two partial unique indexes: terminal rows by run revision, review rows by checkpoint revision. |
| Outbox description and status constraints must be explicit. | `backend/src/intric/database/tables/flow_tables.py:1093-1104` constrains terminal statuses, description format, and source values. | Plan keeps `description = action || ':' || source`, widens `target_status` only to terminal statuses plus review checkpoint states, and names source-constraint widening. |
| Resume must not erase original `started_at`. | `backend/src/intric/flows/infrastructure/flow_run_repo.py:998-1009` writes `started_at` on every queued-to-running claim. | Plan requires `started_at = COALESCE(started_at, now)` and stores resume time on the checkpoint as `resumed_at`. |
| Lifecycle-source rename is too large for the data-model slice. | `rg` found 56 `FlowRunTerminalSource` references across backend source and tests. | Added Slice 9.0a for the mechanical `FlowRunTerminalSource -> FlowRunLifecycleSource` rename with no behavior change. |
| Active checkpoint read permission was ambiguous. | `backend/src/intric/flows/flow_access_policy.py:59-65` already defines flow view permission; review/resume are disabled at `:155-166`. | Plan now uses `FlowApiAction.VIEW` for the active checkpoint read endpoint and `FLOWS_MANAGE` user-principal gates for mutating review/resume endpoints. |
| Output-mode review rejection should not hard-code one string. | `backend/src/intric/flows/enums.py:63-67` owns `FlowOutputMode`; webhook delivery is currently `HTTP_POST`. | Plan adds `flow_output_mode_has_outbound_delivery(mode)` next to `FlowOutputMode` with enum coverage tests. |
| Resume sequencing needs transaction boundaries. | Existing execution claim happens in a later worker transaction after dispatch. | Plan now specifies one resume transaction, post-commit dispatch, then normal queued-to-running claim. |
| Review edit must not change execution hash. | `flow_step_results.flow_step_execution_hash` describes execution, not human edits. | Payload projection rules and Slice 9.4 acceptance now keep the hash immutable during edits. |
| Downstream edited-output propagation needs a behavior test. | `previous_step` and `all_previous_steps` read current step result payloads. | Slice 9.4 now requires an integration test proving edit + approve + resume feeds the edited payload into the next step. |
| PRD wording conflicted with the no-new-resume-task decision. | PRD-003 still referred to a fresh resume task and `waiting_for_review`. | Updated PRD-003 to describe re-queuing the existing execution task, `awaiting_review`, and original/current reviewed output. |

## Decisions

| Topic | Decision | Reason |
|---|---|---|
| Review lifecycle audit | Keep durable outbox for review checkpoint lifecycle, but key rows by checkpoint revision. | This preserves PRD-003's durable lifecycle-audit requirement without forcing checkpoint events into the terminal run-revision key. |
| `started_at` on resume | Preserve original `started_at`; checkpoint owns `resumed_at`. | A resumed worker claim is not a new run start. |
| Rejection terminal status | Use run status `cancelled` with `FlowRunLifecycleSource.REVIEW_REJECTED`. | Operationally the run did not complete; the source disambiguates reviewer rejection from user/admin cancellation. |
| Output side effects | Predicate over `FlowOutputMode`, not a literal `http_post` check. | Future outbound modes must be classified before they can compile with review policy. |

## Verification Still Required

| Slice | Required verification |
|---|---|
| 9.0a | Rename compile/tests and `rg -n "FlowRunTerminalSource" backend/src/intric backend/tests` returning no references. |
| 9.1 | Status predicates, checkpoint table constraints, partial outbox unique indexes, `started_at` preservation, and Alembic compile. |
| 9.2 | Review policy parser errors and `FlowOutputMode` outbound-delivery coverage. |
| 9.3 | Pause/yield, duplicate delivery, and running-only reconciler tests. |
| 9.4 | API permissions, checkpoint CAS/idempotency, edit projection, downstream edited payload, and resume sequencing tests. |
