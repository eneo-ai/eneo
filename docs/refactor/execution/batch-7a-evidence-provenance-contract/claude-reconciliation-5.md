# Claude Reconciliation 5 — 7A.4 Evidence Single-Source Normalization

## Plan Review

Session: `batch-7a-4-evidence-single-source-plan`

Iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted findings:

- The initial single-source claim was too broad while `FlowRunStepPublic.tool_calls_metadata`, the DB column, repository persistence slot, and generated schema still exist.
- RAG tracking state needed an explicit precedence rule across attempts.
- Corrupt provenance markers must be detected from typed `FlowAttemptProvenanceParseResult` values, not by scanning only serialized payload dicts.
- Evidence bundle result tool-call shape needed a single decision: omit result-level `tool_calls_metadata`.
- `default_rag_tracking()` must stay scoped to real RAG sections; no-provenance export summaries need a distinct untracked summary.
- The surviving public read field should expose an OpenAPI deprecation signal.
- Retention cleanup impact needed a quick source audit.

Codex changes:

- Added `Boundary Asymmetry` and `RAG Tracking State Precedence` sections to `plan.md`.
- Chose `derive_rag_usage_tracking()` and `untracked_rag_summary()` as named helpers.
- Added OpenAPI deprecation to the planned source/test scope.
- Added old-row export, corrupt, no-provenance, and OpenAPI behavior pins.
- Audited `data_retention_service.py`; cleanup still updates rows when non-tool debug fields are present or output pruning changes payloads.

Iteration 2 returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

## Implementation Review

Session: `batch-7a-4-evidence-single-source-implementation`

Iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted findings:

- HTTP corrupt RAG state was not pinned.
- Pure-corrupt RAG state branch was untested.
- Mixed corrupt plus valid tracked sources should not report plain `unknown_corrupt` while also listing sources.
- Runtime tool-call source-of-truth needed a positive handshake test, not only a negative result-level assertion.
- `_merge_tracked_rag_summaries()` needed deterministic `selection_basis` / `note` handling and a cleanup of a redundant local variable.

Codex changes:

- Added HTTP assertion for `summary.rag_usage_tracking.tracking_state == "unknown_corrupt"` and `retrieval_tracked is False`.
- Added pure-corrupt unit coverage.
- Added `partial_corrupt` for mixed valid/corrupt RAG evidence and updated the plan/journal accordingly.
- Added a runtime handshake test proving one `StepExecutionOutput.tool_calls_metadata` value lands in attempt provenance and not the completed result.
- Made RAG summary merge deterministic by keeping the first tracked summary values for `selection_basis` and `note`.

Iteration 2 returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

## Codex Judgment

Claude's accepted findings were valid and improved the slice. The implementation now keeps 7A.4 narrow while making the evidence export contract more truthful:

- tool-call evidence has a canonical export owner in attempt provenance
- the public/persisted result field remains only as a deprecated Tier B read surface
- RAG export summaries distinguish not tracked, tracked without sources, tracked with sources, partially corrupt, and fully unknown/corrupt states
- validation and behavior pins cover the new contract at unit, runtime, HTTP, and OpenAPI levels

Remaining risks are documented in `journal.md` and belong to later slices:

- generated frontend evidence types still need 7A.7 alignment
- typed public RAG summary models remain future work
- result-level `tool_calls_metadata` deletion requires a human-approved SDK/frontend reader audit plus persisted-row proof or migration/backfill plan
