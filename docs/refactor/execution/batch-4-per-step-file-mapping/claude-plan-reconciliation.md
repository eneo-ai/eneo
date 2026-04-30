# Batch 4 Claude Plan Reconciliation

## Review Artifact

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-plan-20260430T084017Z.md`
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: `6`

## Accepted Findings

| Claude finding | Local verification | Plan change |
|---|---|---|
| `flow_run_step_result_files` planned an unsupported composite FK to `flow_step_results(flow_run_id, flow_id)`. | `backend/src/intric/database/tables/flow_tables.py:486` only guarantees `(flow_run_id, step_id)` for step results. | Use FK to `flow_step_results.id` plus composite run FKs; do not add the unsupported composite FK. |
| Result-file `source` values used JSON-key names. | `generated_file_ids` is a historical payload key, not a durable domain term. | Use `generated_output` and `declared_artifact`. |
| Runtime has two top-level `file_ids` fallback paths. | `backend/src/intric/flows/runtime/step_input_resolution.py:218` and `:402` both read top-level `file_ids`. | Plan removes both paths. |
| Output file payload serialization owner was incomplete. | `backend/src/intric/flows/runtime/step_execution_runtime.py:277` writes `generated_file_ids`; `:278` writes output `file_ids`. | Add `step_execution_runtime.py` as a Batch 4 owner and validation target. |
| Idempotency algorithm version was handwaved. | Batch 2/PRD-004 require explicit public-contract fingerprinting behavior. | Fingerprint now includes literal `request_fingerprint_algo_version: 1`, tenant, and principal scope. |
| Client wrapper behavior allowed reject-or-ignore ambiguity. | PRD-003 requires removed top-level `file_ids` to be rejected, not silently preserved or dropped. | Plan requires `intric-js` to reject top-level `file_ids` with `flow_run_top_level_file_ids_not_supported`. |
| JSON snapshot and relational projection equality was unpinned. | Batch 4 adds relational projection rows while keeping JSON snapshot as public evidence/idempotency envelope. | Add integration behavior pin asserting the two representations match deterministically. |
| Old `test_typed_io_run_service.py` contract needed an explicit green-state rewrite. | The current file protects removed top-level behavior. | Plan rewrites it into step-scoped happy-path and negative-contract assertions. |
| Active old-shape rows require a stop condition. | Runtime fallback deletion is unsafe if queued/running old-shape rows exist. | Count proof now stops the batch if active top-level rows are found. |

## Partially Accepted Findings

| Claude finding | Decision | Evidence / reason |
|---|---|---|
| AI Builder `file_ids` examples may emit old run-create payloads. | Partially accepted. Batch 4 will not touch AI Builder chat/session attachment contracts unless implementation evidence finds an actual Flow run-create example. | `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:203` is `SendMessageRequest`; `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1068` stores conversation message attachment metadata. These are not Flow run-create payloads. |
| Add database-enforced tenant/file FK now. | Partially accepted as tracked debt, not immediate shared-table scope. | `files` lacks a unique `(id, tenant_id)` target. Batch 4 enforces ownership before persistence and stores tenant on mapping rows. Add a composite files uniqueness constraint before any non-Flow writer or direct mapping endpoint. |

## Rejected Alternatives

| Alternative | Reason |
|---|---|
| Use a single generic mapping table for inputs and outputs. | PRD-003 explicitly names `flow_run_step_input_files` and `flow_run_step_result_files`; separate tables keep request/input and result/output lifecycles clearer. |
| Derive all mapping rows from JSON lazily instead of persisting projections. | PRD-003 requires attempt-scoped mappings. Persisted rows give queryable lineage, constraints, and future rerun/review ownership. |
| Keep a compatibility adapter for top-level `file_ids`. | The system is pre-production and the acceptance criteria require removal unless count proof shows real persisted/public risk. |

## Follow-Up For Verification Pass

Ask Claude to verify:

- the FK design now matches current table constraints,
- both runtime fallback paths are explicitly removed,
- idempotency versioning is public and deterministic,
- AI Builder exclusions are properly evidenced,
- stop conditions and validation commands are sufficient before implementation.
