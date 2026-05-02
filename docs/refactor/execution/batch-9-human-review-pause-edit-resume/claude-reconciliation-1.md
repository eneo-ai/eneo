# Batch 9 Claude Reconciliation 1

TL;DR:
1. Claude returned `GREEN_LIGHT: no` for the first Batch 9 plan review.
2. The valid blockers were incorporated into `plan.md` before implementation.
3. The run and checkpoint wait state now use the same `awaiting_review` spelling.
4. Resume now has explicit checkpoint revision, run revision, and idempotency ownership.
5. Webhook ordering, evidence versioning, permissions, and frontend status ownership are no longer deferred.

## Review Artifact

Reconciliation 2 supersedes the source-rename slice placement and the outbound-output-mode rejection wording. This document preserves the first review pass decisions.

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-9-human-review-plan-20260502T152839Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `7` |

## Accepted Findings

| Finding | Local verification | Plan revision |
|---|---|---|
| Use one wait-state name. | The plan mixed run `waiting_for_review` with checkpoint `awaiting_review`. | Standardized on `awaiting_review` for both run status and active checkpoint state. |
| Define resume CAS and idempotency now. | `backend/src/intric/database/tables/flow_tables.py:374-380` already documents `FlowRuns.revision` as the rerun/resume CAS token. | Added `expected_checkpoint_revision`, checkpoint revision increments, run `awaiting_review -> queued` CAS, and `flow_run_review_checkpoints.resume_idempotency_key`. |
| Block rerun while a run awaits review. | Rerun already depends on run status and revision semantics introduced in Batch 8. | Slice 9.1 now pins that rerun remains status-blocked while a run is `awaiting_review`. |
| Preserve original output while projecting edited output. | `backend/src/intric/flows/runtime/variable_resolver.py:81` and `backend/src/intric/flows/runtime/step_input_resolution.py:238` consume current step result payloads for downstream inputs. | Checkpoints own immutable `original_payload_json` and mutable `current_payload_json`; edits update `flow_step_results.output_payload_json` as the current projection. |
| Decide webhook ordering before runtime implementation. | `backend/src/intric/flows/runtime/executor.py:698-720` currently delivers step webhooks after successful step persistence. | Parser rejects `review_policy` on `output_mode="http_post"` steps until reviewed webhook delivery exists. |
| Resume through the existing executor path. | `backend/src/intric/flows/infrastructure/flow_run_repo.py:998-1009` claims only queued runs. | Resume CASes the run back to `queued` and dispatches existing `flows.execute`; Batch 9 excludes a separate `flows.resume` task. |
| Keep stale-running reconciliation as running-only. | `backend/src/intric/flows/infrastructure/flow_run_repo.py:592-608` only lists `running` runs. | Slice 9.3 now states no behavioral change is required, only a predicate-pinning test. |
| Drop duplicate payload names. | The initial plan used `editable_payload` and `edited_payload`. | Replaced them with `original_payload_json` and `current_payload_json`. |
| Pin review/resume permissions before routes ship. | `backend/src/intric/roles/permissions.py` has no `FLOWS_REVIEW`; `backend/src/intric/flows/flow_access_policy.py:155-166` keeps review/resume unimplemented with empty permission tuples. | Slice 9.4 requires `FLOWS_MANAGE` before setting `implemented=True`; service-key principals stay denied. |
| Avoid terminal-only naming for review lifecycle sources. | `backend/src/intric/flows/enums.py:143-156` currently names `FlowRunTerminalSource`. | Slice 9.1 now replaces terminal-only source naming with `FlowRunLifecycleSource` without compatibility aliases. |
| Centralize frontend run status sets. | Status logic is duplicated in `flowRunProgress.ts`, `flowRunStatusPresentation.ts`, and `FlowRunsTable.svelte`. | Slice 9.6 adds one `flowRunStatusSets.ts` owner used by progress, badge, and polling logic. |
| Name the checkpoint idempotency owner. | `FlowRuns.idempotency_key` is run creation state, not review-resume state. | Slice 9.1 adds `flow_run_review_checkpoints.resume_idempotency_key`. |
| Clarify audit outbox ownership. | `backend/src/intric/database/tables/flow_tables.py:1093-1096` currently constrains `flow_run_audit_outbox.target_status` to terminal statuses. | Slice 9.1 generalizes the table into a Flow run lifecycle audit outbox before review events use it. |
| Make evidence schema change explicit. | `backend/src/intric/flows/flow_run_evidence_export_manifest.py` currently owns the export manifest version. | Slice 9.5 now bumps the manifest schema to `flow-evidence-export.v5`. |
| Keep step result status completed. | `flow_step_results.status` should not model review lifecycle. | Slice 9.2 and 9.3 now state reviewed step results remain `completed`; checkpoint state owns review lifecycle. |

## Not Adopted

| Suggestion | Decision | Reason |
|---|---|---|
| Add a reciprocal code comment between `FlowCareDataPolicy` and the new review policy module. | Do not add by default. | The boundary is encoded in type/module ownership and tests. A comment should be added only if the code path remains easy to confuse after naming and placement. |
| Add `FlowRun.active_review_checkpoint_id`. | Defer. | The initial data model can enforce one active checkpoint per run through checkpoint state/indexes. Add a direct FK only if read-path complexity appears in implementation. |
| Generate frontend status sets directly from OpenAPI. | Defer generation. | Slice 9.6 will first centralize handwritten status sets in one TS module using generated status types; full generation is extra tooling work outside the critical runtime slice. |

## Verification Still Required

| Slice | Required verification |
|---|---|
| 9.1 | Status predicate tests, checkpoint data model tests, repository CAS tests, audit outbox constraints, and Alembic compile check. |
| 9.2 | Review policy parser tests, malformed policy errors, and `review_policy` plus `http_post` rejection. |
| 9.3 | Worker pause/yield tests, duplicate delivery test, and stale-running predicate test. |
| 9.4 | API contract tests, permission matrix tests, stale edit, duplicate resume, already resumed, rejected, cancelled, and approve/resume integration tests. |
| 9.5 | Evidence export tests for original/current review payloads and manifest `v5`. |
| 9.6 | Frontend status presentation tests and review checkpoint component tests. |
