# Batch 4 Claude Reconciliation - Iteration 1

## Claude Result

- Artifact:
  `.codex/artifacts/claude-peer-loop-batch-4-per-step-file-mapping-implementation-20260430T093259Z.md`
- Verbatim attack:
  `docs/refactor/execution/batch-4-per-step-file-mapping/claude-attack-1.md`
- Verdict: `changes_required`
- `GREEN_LIGHT: no`
- Minimum score: `6`

## Findings

| Finding | Classification | Codex action |
|---|---|---|
| PRD literal error code still says `flow_run_legacy_file_ids_not_supported`, while implementation uses `flow_run_top_level_file_ids_not_supported`. | rejected: disagree | The user clarified during this loop that the batch should avoid "legacy" vocabulary/logic because Flows has no production users on this branch. Per protocol, PRDs are not edited mid-loop. `plan.md` and `journal.md` record the human override and the implementation uses the neutral top-level-field error code. |
| Top-level `file_ids` negative pin did not exercise FastAPI/Pydantic request parsing order. | accepted | Moved rejection into `FlowRunCreateRequest.model_validator(mode="before")`, removed the route-handler helper, and added `test_flow_run_create_rejects_removed_top_level_file_ids_before_body_shape_errors` to post a real request with both `file_ids` and malformed `expected_flow_version`. |
| Reserved orchestration key set was duplicated between service and runtime stripping. | accepted | Added `FLOW_RUN_ORCHESTRATION_INPUT_KEYS` to `flow_run_step_inputs.py` and imported it in both the service and runtime resolver. |
| Output payload still wrote the old `file_ids` alias beside `generated_file_ids`. | accepted | Removed the output `file_ids` alias from `build_output_payload`, removed output-alias readers from evidence/export artifact collection, and updated worker/runtime tests to assert the canonical generated/artifact fields only. |
| Migration had redundant single-column `flow_run_id` FKs in addition to composite run/tenant and run/flow FKs. | accepted | Removed the redundant single-column `flow_run_id` FKs from ORM and migration while keeping composite run/tenant and run/flow guards. |
| `attempt_no` default existed on input mappings but not result mappings. | accepted | Added `server_default="1"` to result mapping `attempt_no` in ORM and migration. |
| Defensive `getattr(request, "json", None)` was dead code. | accepted | Removed the route-handler helper entirely by moving the removed-shape rejection into the request model. |
| `request_fingerprint_algo_version` is hashed but not stored in its own column. | rejected: out-of-scope | Batch 4 needs stable same/different request behavior and no public v1/v2 migration audience exists on this branch. The fingerprint includes the algorithm version. A separate persisted version column can be revisited if a future batch introduces multiple active fingerprint algorithms. |
| `declared_artifact` precedence over `generated_output` needed an explicit invariant. | accepted | Added a short source comment at the overwrite point in `FlowRepository._result_file_sources`. |
| Full backend test coverage question. | rejected: out-of-scope | The loop runs the exact Batch 4 validation commands plus focused pins. A broader full backend pass is not required for this batch and the known local WeasyPrint native dependency failure is already classified separately. |

## Resulting Changes

- Backend request-model validation now rejects removed top-level `file_ids`
  before unrelated body-shape errors.
- Runtime/source ownership for reserved orchestration keys is centralized.
- New output payloads no longer write or read the removed output `file_ids`
  alias.
- Mapping table constraints are tighter and symmetric.
- Additional focused API/model/runtime tests cover the accepted fixes.

## Gate

Accepted findings existed, so the loop returns to validation as Iteration 2.
