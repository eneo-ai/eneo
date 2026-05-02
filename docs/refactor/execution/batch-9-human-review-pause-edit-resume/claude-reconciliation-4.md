# Batch 9 Claude Reconciliation 4

TL;DR:
1. Claude required changes on the first Slice 9.1 implementation review.
2. The blocking findings were valid for cancellation, checkpoint step ownership, method naming, and audit description drift.
3. The implementation now terminalizes `awaiting_review` cancellation, removes the checkpoint FK to mutable `flow_steps`, and shares audit description formatting.
4. Claude returned `GREEN_LIGHT: yes` after the revision.
5. Remaining notes are accepted forward debt for Slice 9.2 and Slice 9.4.

## Review Artifacts

| Iteration | Artifact | Verdict | Green light | Minimum score |
|---|---|---:|---:|---:|
| 1 | `.codex/artifacts/claude-peer-loop-batch-9-slice-9-1-review-checkpoint-data-model-20260502T162800Z.md` | `changes_required` | `no` | `7` |
| 2 | `.codex/artifacts/claude-peer-loop-batch-9-slice-9-1-review-checkpoint-data-model-verification-20260502T163623Z.md` | `green` | `yes` | `8` |

## Accepted Changes

| Finding | Resolution |
|---|---|
| `terminalize_run_status` did not allow `awaiting_review -> cancelled`. | `FlowRunRepository.terminalize_run_status` now uses cancellable source statuses for `target_status=CANCELLED`, and the integration test covers cancellation through `FlowRunTerminalizer`. |
| Checkpoints were tied to mutable `flow_steps` through an FK. | `flow_run_review_checkpoints.step_id` remains a runtime snapshot UUID without a `flow_steps` FK; Slice 9.2 must validate it against the run's published flow version before insert. |
| `create_or_get_review_checkpoint` hid which conflict path it absorbs. | The repository method is now `create_or_get_review_checkpoint_for_attempt`. |
| Audit outbox `description` formatting was duplicated. | `flow_run_audit_description(action, source)` is used by terminalization, review checkpoint outbox insertion, and the integration test. |
| Checkpoint audit target status relied on the shared `"cancelled"` value by accident. | `FLOW_RUN_AUDIT_TARGET_STATUS_VALUES` is built from terminal run statuses plus all checkpoint states with deterministic de-duplication. |
| Requester coverage only used user principals. | The repository integration suite now covers a service-key requester with `requester_user_id=None`. |

## Rejected Or Deferred

| Claude suggestion | Decision |
|---|---|
| Split audit outbox target into separate run-status and checkpoint-state columns. | Deferred. Batch 9's accepted audit plan uses a single `target_status` plus `review_checkpoint_id` discriminator; this remains a known smell to revisit before audit volume grows. |
| Remove `schema_version`. | Rejected for this slice. Slice 9.1 acceptance explicitly requires schema version ownership on the checkpoint table. |
| Make the migration downgrade destructive or one-way. | Rejected. The downgrade remains non-destructive and may require a manual pre-step if rows already use `awaiting_review` or review checkpoint audit values. |
| Replace schema-introspection tests with only DB behavior tests. | Rejected for now. The unit tests deliberately fence canonical enum/check/index shape while integration tests cover behavior. |

## Forward Debt

| Owner slice | Debt | Acceptance note |
|---|---|---|
| Slice 9.2 | Validate checkpoint `step_id` against the run's `flow_version` published definition before insertion. | The repository stores historical UUIDs and does not FK to mutable `flow_steps`. |
| Slice 9.2/9.4 | Enforce requester/decider principal pairing in the service layer. | `USER` should carry a user id; service-key requester rows intentionally do not. |
| Slice 9.4/runbook | Document downgrade preconditions for active `awaiting_review` data. | Downgrade is non-destructive and cannot silently rewrite active review state. |
| Future audit cleanup | Revisit single `target_status` when checkpoint audit volume grows. | A split target column model may be cleaner later, but it is not required to land Slice 9.1. |

## Implementation Gate

Slice 9.1 is implementation-ready after local validation and Claude green light.
