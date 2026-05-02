# Claude Reconciliation 6 — Repository Command Plan

## Claude Verdict

- Artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-repository-command-plan-20260502T110016Z.md`
- Verdict: changes required
- Green light: no
- Minimum score: 7

## Accepted Changes

| Claude point | Codex action | Evidence |
|---|---|---|
| Fresh rerun acceptance must be one transaction. | Added an explicit repository command contract requiring operation insert, invalidated rows, run reset, revision bump, and step-result resets to commit or roll back together. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Idempotent operation insert pattern was unspecified. | Pinned PostgreSQL `ON CONFLICT DO NOTHING` plus select fallback against `uq_flow_run_rerun_operations_request_fingerprint`. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Rerun vs retry boundary was implicit. | Documented rerun as replacement of completed current output; failed/currently active roots return `flow_run_rerun_step_incomplete` or invalid transition. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Reset columns were incomplete. | Added column-by-column reset tables for `FlowRuns` and `FlowStepResults`, plus explicit preserve lists. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Invalidated-step row semantics were under-specified. | Added deterministic role, order, dependency source, prior result, prior attempt, and deferred new-attempt rules. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Operation revision semantics were unclear. | Defined `expected_run_revision`, `accepted_run_revision`, and `FlowRuns.revision = accepted + 1`. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |
| Test plan missed rollback/concurrency/tenant/runtime-alias cases. | Added these scenarios to the Slice 8.5 test list. | `docs/refactor/execution/batch-8-step-rerun/plan.md` |

## Decision

The next implementation slice remains repository-first. API exposure stays deferred until the command exists and the persistence invariants are green.
