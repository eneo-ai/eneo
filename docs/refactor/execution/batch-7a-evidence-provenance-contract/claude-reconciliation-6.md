# Claude Reconciliation 6 — 7A.5 Retention Tombstones And Deletion Semantics

## Plan Review

Session: `batch-7a-5-retention-tombstones-plan`

Iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted findings:

- Attempt retention markers needed an explicit schema version and parser branch so retention-purged evidence would not be reported as corrupt.
- `EvidenceProvenancePersistedVersionStatus` needed the `retention_purged` public contract state.
- Cleanup idempotency needed a two-pass test with zero second-pass changed counts.
- Cleanup needed per-row tenant/run/trace/cutoff/policy context instead of bare run-id sets.
- Missing-artifact reconciliation needed to preserve tombstones and skip tombstone-only payloads.
- Tombstone key, actor source, redaction behavior, and pre-7A.5 already-purged ambiguity needed explicit plan treatment.

Iteration 2 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted findings:

- The test matrix needed to pin parser, cleanup, reconciliation, manifest, RAG, HTTP, OpenAPI, and deterministic-note behavior.
- Tombstone counts needed typed per-marker logical counts, not batch-row counts.
- `redacted_for_deletion_count` should remain explicit and zero until tenant/DSAR deletion markers exist.
- A future persisted attempt-state envelope should be carried forward if more schemas are added.

Iteration 3 returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Codex changes:

- Updated `plan.md` with explicit marker schema versions, status literals, idempotency behavior, RAG precedence, redaction behavior, OpenAPI pins, and validation commands.
- Recorded the pre-implementation collision grep for `flow_retention_tombstones`, `flow-retention-tombstone`, and `flow-attempt-retention-marker`.

## Implementation Review

Session: `batch-7a-5-retention-tombstones-implementation`

Iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted findings:

- The invalid attempt-retention marker parser branch was not tested.
- Tombstone `counts` was still a typed bag rather than per-marker count models.
- `artifact_content_purged_count` was defaulted while sibling counts were required.
- Attempt retention counts used the database column name `provenance_json` instead of logical count vocabulary.
- `derive_rag_usage_tracking()` still read like it patched retention-purged counts after the fact.
- The generated frontend schema drift and broader `tool_calls_metadata` cleanup needed explicit carry-forward.

Codex changes:

- Added `RunDebugStepResultRetentionCounts`, `RunDebugAttemptRetentionCounts`, and `GeneratedArtifactRetentionCounts`, with marker-shape validation in `FlowRetentionTombstone`.
- Added invalid retention-marker parser coverage.
- Made `artifact_content_purged_count` required.
- Changed attempt retention counts to `cleared_field_count`.
- Cleaned `derive_rag_usage_tracking()` so `retention_purged_attempt_count` is assigned once at the summary boundary.
- Removed public `FlowRunStepPublic.tool_calls_metadata` instead of keeping a deprecated Flow compatibility surface.
- Replaced the evidence-bundle inline exclude set with `_RESULT_FIELDS_REPLACED_BY_ATTEMPT_PROVENANCE`.

Iteration 2 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted findings:

- The RAG retention count assignment still had two branch-local writes.
- The `tool_calls_metadata` deletion sweep was not recorded with a PRD/batch owner.
- The journal lacked 7A.5 implementation, validation, and carry-forward evidence.

Codex changes:

- Hoisted `retention_purged_attempt_count` to a single tail assignment in `derive_rag_usage_tracking()`.
- Added the 7A.5 implementation, validation, and carry-forward sections to `journal.md`.
- Assigned the full `tool_calls_metadata` deletion sweep to existing PRD-008 / Batch 10 cleanup.

Iteration 3 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted findings:

- The new 7A.5 journal content was accidentally nested under the 7A.4 heading.
- The `tool_calls_metadata` deletion carry-forward needed concrete file paths.
- The PRD-008 / Batch 10 anchors needed verification.

Codex changes:

- Reorganized `journal.md` so 7A.5 has one `Iteration 6` section with plan reviews, implementation summary, validation summary, carry-forward risks, and implementation review in order.
- Added concrete `tool_calls_metadata` deletion sites and the blocking `runtime/executor.py` dependency.
- Linked the carry-forward to `docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md:18` and `docs/refactor/implementation-order.md:25`.

Iteration 4 returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

## Codex Judgment

Claude's accepted findings were valid and improved the slice. The final 7A.5 implementation keeps retention/deletion semantics inside existing evidence owners while making destructive retention reviewable:

- Retention tombstone schema and typed count shapes have one canonical owner.
- Cleanup writes idempotent, PII-free markers before destructive pruning.
- Evidence exports distinguish corrupt, tracked, and retention-purged attempt provenance.
- Retention summary counts are typed and deterministic.
- RAG summaries report retention-purged attempts explicitly.
- Public Flow step responses no longer expose deprecated result-level tool-call metadata.
- The remaining `tool_calls_metadata` deletion sweep is concrete, anchored, and deferred to the existing PRD-008 / Batch 10 cleanup path because runtime provenance still depends on the internal field.

Remaining risks are documented in `journal.md` and belong to later slices:

- generated frontend schema drift belongs to 7A.7
- artifact/file row ownership belongs to 7A.6
- full persisted/domain `tool_calls_metadata` deletion belongs to PRD-008 / Batch 10
- pre-7A.5 already-purged rows require a human-approved migration/backfill decision if exact historical classification becomes necessary
