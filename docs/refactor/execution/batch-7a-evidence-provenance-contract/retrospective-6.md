# Batch 7A.5 Retrospective — Retention Tombstones And Deletion Semantics

## A. Plan adherence

- pass — Implemented the active 7A.5 plan in `plan.md`: destructive retention cleanup now writes typed tombstones/markers, evidence export reports retention state from those markers, and no new evidence ledger or migration was introduced.
- pass — Used the planned canonical owners: `FlowStepAttempts.provenance_json`, `FlowStepResults.output_payload_json`, `Files`, `flow_run_provenance.py`, `flow_run_export_json.py`, and the typed manifest model.
- pass — Scope expanded only for directly related cleanup: the public `FlowRunStepPublic.tool_calls_metadata` deprecation surface from 7A.4 was removed because Flow/Flow AI Builder are unreleased.
- pass — Did not start Batch 8 rerun, Batch 9 review, frontend evidence UI, migrations, package rename, or `intric.*` namespace migration.

## B. Acceptance criteria

- pass — Cleanup idempotency is pinned by two consecutive `cleanup_old_flow_runtime_data()` calls returning zero second-pass debug/artifact changes.
- pass — Attempt retention markers parse as `retention_purged`; invalid retention markers parse as corrupt with `flow_attempt_provenance_invalid_retention_marker`.
- pass — Manifest precedence is pinned: corrupt beats retention-purged, retention-purged beats tracked, tracked beats not-tracked.
- pass — Retention summary counts tombstones, retention-purged markers, artifact-content-purged tombstones, and keeps redacted-for-deletion explicit at zero.
- pass — RAG tracking reports `retention_purged_attempt_count` without conflating retention-purged evidence with never-tracked evidence.
- pass — Public HTTP evidence export pins corrupt plus tombstone precedence.
- pass — OpenAPI pins the widened manifest status enum, the required artifact-content-purged count, and absence of public result-level `tool_calls_metadata`.

## C. Behavior pins and validation

- pass — Focused tests passed: `88 passed, 16 warnings` for cleanup/unit/OpenAPI/model coverage and `3 passed, 16 warnings` for HTTP evidence pins with the local testcontainers fallback.
- pass — Static validation passed: pyright 0 errors, ruff check clean, ruff format check clean, import-linter contracts kept, collision grep only expected schema literals, anti-slippage grep clean, and `git diff --check` clean.
- pass with environment caveat — Docker validation remains blocked by the local Codex approval policy before Docker execution. Local/testcontainers validation is the recorded fallback.

## D. Pre-production deletion discipline

- pass — Removed the 7A.4 public Flow `tool_calls_metadata` deprecation surface instead of preserving a deprecated compatibility field.
- pass — Did not add a legacy reader for unversioned branch-local provenance; invalid/unversioned provenance remains corrupt evidence.
- pass — Full persisted/domain `tool_calls_metadata` deletion is recorded under PRD-008 / Batch 10 with concrete file paths because deleting it piecemeal would break current attempt-provenance construction.
- pass — No source compatibility shim, `legacy_*` path, `deprecated=True`, or broad fallback was added by this slice.

## E. Single source of truth

- pass — `flow_retention_tombstone.py` is the canonical owner for tombstone schema versions, marker wrappers, actor source, typed count shapes, and extraction/appending helpers.
- pass — Attempt provenance parsing stays in `flow_run_provenance.py`.
- pass — Export manifest summary derivation stays in `flow_run_export_json.py`.
- pass — Artifact file-row ownership remains explicitly deferred to 7A.6 instead of adding a parallel artifact evidence system in 7A.5.

## F. File splits and naming

- pass — New file `flow_retention_tombstone.py` has a narrow domain-specific responsibility and one reason to change.
- pass — No generic `utils`, `helpers`, `common`, `manager`, `processor`, `types`, or `constants` file was added.
- pass — `_RESULT_FIELDS_REPLACED_BY_ATTEMPT_PROVENANCE` names the current result-field omission without adding a restating comment.

## G. Comments and readability

- pass — No source comments were added for Codex, Claude, plan mechanics, or batch process.
- pass — New source uses names and typed models instead of explanatory "what" comments.
- pass — Journal carry-forward is concrete enough for a later reviewer to act on without rediscovering the file set.

## H. Test quality

- pass — Tests assert behavior through retention cleanup, parser results, export payloads, HTTP response shape, OpenAPI schema, and public Pydantic model parsing.
- pass — No internal collaborator mocks were added.
- pass — No snapshot tests or private-helper call assertions were added.

## I. Boundary discipline

- pass — Routers remain thin; no HTTP exception was introduced in domain/application logic.
- pass — Data-retention mutation stays in `DataRetentionService`; marker shape stays in the Flow tombstone value object.
- pass — Pydantic schemas remain at JSON/export/API boundaries; SQLAlchemy models remain persistence details.
- pass — Import-linter confirms the new Flow module does not break architecture contracts.

## J. Scope and risk

- pass — The only broader cleanup taken in this slice was removal of the public deprecated Flow tool-call read field, which is directly tied to the evidence single-source work.
- pass — Remaining `tool_calls_metadata` cleanup is deliberately recorded for PRD-008 / Batch 10 because `runtime/executor.py` still reads it into attempt provenance.
- pass — Remaining ambiguity for pre-7A.5 already-purged rows is recorded as a migration/backfill decision, not hidden as tracked evidence.

## Final gate

GREEN — 0 fails.
