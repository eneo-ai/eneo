# Batch 8 — Claude Reconciliation 1

TL;DR:
1. Claude did not green-light the initial plan.
2. The DAG critique is valid: runtime dependencies come from template references, not only `input_source`.
3. The plan now removes dual idempotency and attempt-allocation sources.
4. Rerun operation rows are the Batch 8 audit owner; shared audit action/outbox changes are out.
5. The revised plan adds `FlowRuns.revision` and `FlowStepResults.current_attempt_no`.

## Claude Artifact

`.codex/artifacts/claude-peer-loop-batch-8-step-rerun-plan-20260502T093512Z.md`

## Accepted Findings

| Finding | Verdict | Evidence | Plan change |
|---|---|---|---|
| DAG must include template-derived references. | Accepted | `backend/src/intric/flows/runtime/step_input_resolution.py:163-201`, `backend/src/intric/flows/runtime/http_orchestration.py:129-155`, `backend/src/intric/flows/runtime/http_orchestration.py:296-328`, `backend/src/intric/flows/runtime/template_fill_runtime.py:402-431`, `backend/src/intric/flows/runtime/step_execution_runtime.py:666-675` all interpolate runtime context. | `flow_run_rerun_graph.py` now scans `input_source`, `input_bindings`, HTTP input/output config templates, template-fill bindings, and assistant snapshot instructions. |
| Audit owner was hedged. | Accepted | `backend/src/intric/database/tables/flow_tables.py:759-821` and `backend/src/intric/database/tables/flow_tables.py:795` make terminal outbox one row per run. | Rerun operation rows are the Batch 8 audit owner. No `ActionType.FLOW_RUN_RERUN_REQUESTED`, no rerun `audit_service.log_async`, and no terminal outbox widening. |
| `idempotency_key` plus fingerprint creates two idempotency sources. | Accepted | Create-run idempotency uses a key/fingerprint pair, but PRD-003 asked for endpoint-specific deterministic rerun idempotency. | Removed `idempotency_key` from the planned operation table. `request_fingerprint` is the unique replay key. |
| `planned_attempt_no` plus executor allocation creates two attempt sources. | Accepted | `backend/src/intric/flows/runtime/executor.py:524-535` currently uses Celery retry count, which the plan already intended to replace. | Operation row stores `root_attempt_no` allocated under run lock. Executor reads it and repository allocates downstream attempt numbers under the operation/run lock. |
| `expected_run_updated_at` is a weak revision token. | Accepted | `backend/src/intric/database/tables/base_class.py:35-39` updates `updated_at` on ordinary row updates. | Add `FlowRuns.revision`; API uses `expected_run_revision`. |
| Current result files can leak after a result row reset. | Accepted | `backend/src/intric/database/tables/flow_tables.py:526-528` has one result row per run/step, and `backend/src/intric/database/tables/flow_tables.py:695-697` attaches files to that row. | Add `FlowStepResults.current_attempt_no`; current step APIs filter files by current attempt while evidence/export include all attempt-scoped files. |
| Service-key rerun fields would be dead-on-write. | Accepted | `FlowApiAction.RERUN` is being enabled only for user principals with `FLOWS_MANAGE`. | Drop `requested_by_api_key_id` from planned rerun operations. |
| Live `FlowStepDependencies` non-use should be pinned. | Accepted | Scoped search found only `backend/src/intric/database/tables/flow_tables.py:193-235`. | Add `test_flow_rerun_architecture.py` to assert rerun graph code does not read the live dependency table. |

## Rejected Or Deferred Findings

| Finding | Decision | Reason |
|---|---|---|
| Materialize version-scoped step dependencies now. | Deferred. | A pure graph module over the published snapshot is enough for Batch 8 and easier to review. A version-scoped materialization can be a later optimization if rerun graph cost becomes measurable. |
| Add a per-operation status read endpoint now. | Deferred. | Batch 8 keeps public status ownership in run and step projections. The operation row is returned on rerun request and included in evidence/export; no separate frontend operation-state owner is introduced. |

## Plan Revisions

- Renamed the plan to Iteration 2.
- Added source evidence for template-derived dependencies, run revision, result-file leak risk, and audit outbox shape.
- Replaced `expected_run_updated_at` with `expected_run_revision`.
- Replaced operation `idempotency_key` with deterministic `request_fingerprint`.
- Replaced `planned_attempt_no` with operation-owned `root_attempt_no` plus attempt ids.
- Added `FlowRuns.revision` and `FlowStepResults.current_attempt_no`.
- Made rerun operation rows the sole Batch 8 rerun audit owner.
- Added architecture and DAG tests for template references and live dependency-table non-use.

## Confidence

High. The accepted findings are directly supported by source evidence and remove ambiguity before implementation starts.
