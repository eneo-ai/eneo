# Batch 8 — Claude Reconciliation 2

TL;DR:
1. Claude green-lit the revised Batch 8 step-rerun plan.
2. The remaining feedback was clarification-level, not blocking.
3. The plan now closes active rerun operations during terminalization.
4. The plan removes the redundant `flow_run_rerun_conflict` error code.
5. The plan pins dispatch recovery, revision writes, `current_attempt_no` backfill, and rerun dependency kinds before implementation.

## Claude Artifact

`.codex/artifacts/claude-peer-loop-batch-8-step-rerun-plan-verification-20260502T094549Z.md`

## Verdict

| Field | Value |
|---|---|
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |
| Confidence | High |

## Accepted Clarifications

| Clarification | Verdict | Evidence | Plan change |
|---|---|---|---|
| Active rerun operations need a terminal rule when the run is cancelled or terminalized. | Accepted | `backend/src/intric/flows/application/flow_run_terminalization.py:33-198` owns terminal transitions. | Operation status includes `cancelled`; terminalization marks active rerun operations `cancelled` for cancelled runs or `failed` with `failure_code = "run_terminalized"` for failed terminalization. |
| `flow_run_rerun_conflict` is redundant unless a real sequence can produce it. | Accepted | The plan's run-locked revision bump means same-fingerprint requests replay and different requests see stale revision. | Removed the public `flow_run_rerun_conflict` code from the Batch 8 API plan. |
| `FlowStepResults.current_attempt_no` needs migration backfill. | Accepted | `backend/src/intric/database/tables/flow_tables.py:526-528` has one result row per run/step and result files are attempt-numbered. | Migration will backfill completed result rows with `current_attempt_no = 1`. |
| `FlowRuns.revision` bump paths must be explicit. | Accepted | `backend/src/intric/database/tables/base_class.py:35-39` makes `updated_at` display metadata, not a compare-and-swap token. | Batch 8 bumps revision on rerun acceptance and on lifecycle writes it touches for queued-to-running, terminalization, and cancellation. |
| The operation unique constraint duplicated `requested_by_user_id` already encoded in the fingerprint. | Accepted | The deterministic fingerprint includes the user principal. | Unique constraint is now `(tenant_id, flow_run_id, request_fingerprint)`. |
| `dependency_sources_json` needs pinned values despite being evidence-only JSON. | Accepted | Runtime interpolation happens across input bindings, HTTP config fields, template-fill bindings, and assistant instructions. | Added `RerunDependencyKind` values and required tests to pin the emitted list. |
| Dispatch recovery must be tested against stale queued redispatch. | Accepted | `backend/src/intric/flows/application/flow_dispatch.py:47-66` terminalizes create-run dispatch failures, while `backend/src/intric/flows/application/flow_run_service.py:690-757` redispatches stale queued runs. | Plan requires rerun-aware recoverable dispatch behavior and an integration test covering dispatch failure to redispatch to active-operation reload. |
| Lack of a standalone operation-status endpoint is a deliberate UX trade-off. | Accepted | Batch 8 keeps public status ownership in run/step projections. | Added a risk row documenting that rerun operation failure is observed through run/step state, with operation details in response and evidence/export. |

## Rejected Or Deferred Findings

| Finding | Decision | Reason |
|---|---|---|
| Add a standalone rerun operation status endpoint now. | Deferred. | It would introduce a second public status owner in Batch 8. Run and step projections remain the public status source. |
| Materialize version-scoped dependency rows now. | Deferred. | The published-definition graph module is sufficient for Batch 8 and easier to review. Materialization can be reconsidered if Batch 9 needs a shared dependency cache. |

## Implementation Pins

- Do not call the existing create-run `dispatch_flow_run_after_commit` path for rerun unless it has an explicit recoverable dispatch mode.
- Do not add a public `flow_run_rerun_conflict` code without a concrete reachable sequence and a behavior test.
- Do not store free-form dependency source strings; emit the pinned `RerunDependencyKind` values.
- Do not leave active rerun operations non-terminal after run terminalization.

## Confidence

High. The accepted clarifications are small, directly supported by source evidence, and reduce ambiguity before source implementation starts.
