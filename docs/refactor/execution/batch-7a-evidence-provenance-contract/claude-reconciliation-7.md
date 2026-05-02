# Claude Reconciliation 7 — 7A.6 Artifact/File Evidence Ownership

## Plan Review

Session: `eneo-flow-7a6-artifact-file-evidence`.

Iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted findings:

- Known artifact rows with purged content need a distinct 410 response and `flow_run_artifact_content_unavailable`.
- Missing artifact rows remain 404 with `flow_run_artifact_not_found`.
- Artifact availability means `Files.blob` or `Files.text` exists; transcription is not downloadable artifact content.
- Signed artifact access must re-check file content after the result-row lookup before issuing a URL.
- `_reconcile_missing_generated_artifact_references()` should be deleted unless implementation proves a real row-backed failure mode.
- JSON artifact keys are frontend display payload only and need a 7A.7 deletion condition.
- Row ordering, duplicate source precedence, latest-attempt step display, terminal-step final-output derivation, and hash inclusion needed explicit rules.
- Manifest artifact availability fields must be strict typed fields, not allowed extras.
- Tests must prove JSON payload artifact references are ignored when no result-file row exists.

Codex changes:

- Updated `plan.md` with 404/410 behavior, blob/text availability, post-lookup race handling, display-cache deletion condition, row ordering, latest-attempt rules, typed manifest fields, and inverse-test requirements.

## Implementation Review

Session: `eneo-flow-7a6-artifact-file-evidence`.

Iteration 2 returned substantive `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

The first iteration-2 artifact used Markdown heading prefixes for the output contract, so the wrapper could not parse `GREEN_LIGHT: yes`. The same Claude session then returned a format-only confirmation with exact contract lines:

- `VERDICT: green`
- `GREEN_LIGHT: yes`
- `MIN_SCORE: 8`

Claude confirmed:

- `FlowRunStepResultFiles` joined to `Files` is the only artifact evidence reader for export, signed access, and retention cleanup.
- 404 vs 410 behavior is correct and machine-readable.
- The service re-checks file content before signing, closing the retention race.
- `bundle.result_files` is part of the hashed export payload.
- Artifact availability summary is strict, typed, and row-backed.
- Retention cleanup works without payload artifact references.
- The inverse JSON-ignored service test is present.
- No deprecated, legacy, backwards-compatible, or process-comment surface was added for unreleased Flow / Flow AI Builder.
- 7A.7 generated/frontend alignment is documented instead of hand-editing generated TypeScript in this backend slice.

## Codex Judgment

Claude's accepted plan findings were valid and improved the slice. The final 7A.6 implementation makes artifact evidence ownership single-sourced:

- Row association lives in `FlowRunStepResultFiles`.
- File metadata and content availability live in `Files`.
- `FlowRunRepository` exposes a narrow typed result-file projection.
- `FlowRunService` owns access checks and artifact signing eligibility.
- Evidence bundle/export code consumes `result_files`.
- Retention cleanup uses result-file rows for destructive artifact cleanup.

Remaining risks are documented in `journal.md` and belong to later work:

- 7A.7 generated/frontend evidence alignment.
- 7A.7 deletion of JSON artifact display-cache writers/readers and `_prune_generated_artifact_payload()`.
- A future manifest-builder cleanup to avoid dumping/re-parsing typed result-file rows.
- PRD-008 / Batch 10 full persisted/domain `tool_calls_metadata` deletion.
