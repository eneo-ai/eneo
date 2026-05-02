# Batch 7A.6 Retrospective — Artifact/File Evidence Ownership

## A. Plan adherence

- pass — Implemented the active 7A.6 plan in `plan.md`: artifact evidence export, signed artifact access, and retention cleanup now read `FlowRunStepResultFiles` joined to `Files`.
- pass — Used the planned canonical owners: `FlowRunStepResultFiles` for row association, `Files` for file metadata/content availability, `FlowRunRepository` for row projection, `FlowRunService` for signing eligibility, and `flow_run_export_json.py` for export summaries.
- pass — Did not start Batch 8 rerun, Batch 9 review, frontend evidence UI/view-model work, generated TypeScript editing, migrations, package rename, or `intric.*` namespace migration.
- pass — Kept JSON artifact keys only as documented display-cache payload until 7A.7 removes current frontend readers.

## B. Acceptance criteria

- pass — `list_result_files()` and `get_result_file()` are row-backed, tenant-scoped, ordered by `step_order`, `attempt_no`, and `ordinal`, and report blob/text availability.
- pass — Signed artifact access ignores payload JSON artifact references without a result-file row.
- pass — Missing artifact row returns `flow_run_artifact_not_found`; known artifact row with purged content returns `flow_run_artifact_content_unavailable`.
- pass — The service re-checks file content after file lookup, so retention cannot race into a signed URL.
- pass — Evidence bundle export payload includes `result_files`, so associated artifact rows are covered by the content hash.
- pass — Manifest artifact availability is strict typed data with row-backed counts and per-artifact metadata.
- pass — Summary, final output, and step overview artifact details are row-backed and follow the latest-attempt rules in the plan.
- pass — Retention cleanup uses result-file rows and still works when display payload artifact keys are absent.

## C. Behavior pins and validation

- pass — Focused unit/OpenAPI tests passed: 57 passed, 16 warnings.
- pass — Focused DB integration tests passed: 4 passed, 16 warnings.
- pass — Static validation passed on the changed files: pyright 0 errors, ruff check clean, ruff format check clean, import-linter contracts kept, deleted-helper grep clean, anti-slippage grep clean, and `git diff --check` clean.
- pass with scope note — Full backend ruff check/format still reports unrelated pre-existing formatting/import-order issues in Alembic history and unrelated tests. The slice validated the changed Python files and did not rewrite unrelated history.

## D. Pre-production deletion discipline

- pass — Deleted payload-derived artifact scanner helpers and the `payload_derived` manifest state.
- pass — Deleted `_extract_generated_file_ids()` and `_reconcile_missing_generated_artifact_references()` instead of keeping JSON artifact evidence compatibility.
- pass — Added no deprecated Flow field, legacy Flow reader, backwards-compatible JSON artifact fallback, or compatibility shim.
- pass — The remaining JSON artifact pruning helper has a concrete 7A.7 deletion condition tied to frontend readers.

## E. Single source of truth

- pass — Artifact row association is canonical in `FlowRunStepResultFiles`.
- pass — Artifact file metadata and content availability are canonical in `Files`.
- pass — Evidence export and signed artifact access no longer scan output payload JSON for artifact ownership.
- pass — Retention cleanup gets artifact file ids from result-file rows, not JSON payload keys.

## F. File splits and naming

- pass — New file `flow_run_step_result_file.py` has one narrow reason to change: the typed result-file projection.
- pass — No generic `utils`, `helpers`, `common`, `manager`, `processor`, `types`, or `constants` file was added.
- pass — New helper names in `flow_run_export_json.py` describe row semantics instead of hiding behavior behind generic names.

## G. Comments and readability

- pass — No source comments were added for Codex, Claude, plan mechanics, or batch process.
- pass — New source relies on names and typed models instead of comments that restate implementation.
- pass — One pre-existing Flow API comment in a touched file was tightened to remove "legacy compatibility" phrasing while preserving behavior.

## H. Test quality

- pass — Tests assert behavior through service outcomes, repository row queries, export payloads, OpenAPI schema, public Pydantic model parsing, and retention cleanup.
- pass — No internal collaborator call-order assertions, snapshots, broad mocks, or tests for deleted JSON-only compatibility behavior were added.
- pass — The inverse test for payload JSON artifacts without rows protects the single-source-of-truth contract.

## I. Boundary discipline

- pass — Routers remain thin and only document the 410 error shape.
- pass — Application logic raises domain/application exceptions, not FastAPI `HTTPException`.
- pass — SQLAlchemy rows stay in the repository; API/export layers consume typed projections.
- pass — Import-linter confirms the change did not break Flow architecture contracts.

## J. Scope and risk

- pass — The only source expansion was directly required for the row-backed artifact contract and HTTP 410 handling.
- pass — Generated `intric-js` schema drift is recorded for 7A.7 instead of hand-edited in this backend slice.
- pass — The future manifest-builder cleanup is low risk and documented: avoid dumping/re-parsing typed result-file rows once the manifest builder is extracted.

## Final gate

GREEN — 0 fails.
