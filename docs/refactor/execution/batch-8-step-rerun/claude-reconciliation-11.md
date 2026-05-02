# Claude Reconciliation 11 — API Contract And Recoverable Dispatch Plan

## Claude Verdict

- Plan review artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-api-dispatch-plan-20260502T124100Z.md`
- Initial verdict: changes required
- Verification artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-api-dispatch-plan-verification-20260502T124545Z.md`
- Verification verdict: green
- Green light: yes
- Minimum score: 8

## Accepted Changes

| Claude point | Codex action | Evidence |
|---|---|---|
| A top-level `file_ids` validator would preserve a never-shipped rerun shape. | Replaced the validator plan with `ConfigDict(extra="forbid")` and unknown-key OpenAPI coverage. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Reason length and revision lower bound should be structural API constraints. | Planned `Field(min_length=1, max_length=1024)` for `reason` and `Field(ge=1)` for `expected_run_revision`. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Full duplicate dispatch helpers would create drift. | Planned one private dispatch core shared by the terminalizing create-run wrapper and recoverable rerun wrapper. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Stale revision must not schedule dispatch. | Added a router test requirement for stale-revision propagation with no background dispatch task. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Replay response semantics needed to be explicit. | Added current-persisted-run replay semantics to the plan and required OpenAPI descriptions/tests. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| The endpoint belongs with run lifecycle routes. | Moved the planned owner from `flow_run_steps_router.py` to `flow_run_execution_router.py`. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Permission coverage should exercise the endpoint, not only the policy unit. | Added endpoint-level matrix coverage for view/run/original-owner/service-key denial and manage acceptance. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |

## Decision

Slice 8.7 can proceed to implementation against the revised plan.
