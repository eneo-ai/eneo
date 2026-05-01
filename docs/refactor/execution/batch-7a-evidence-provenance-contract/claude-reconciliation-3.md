# Claude Reconciliation 3 — Typed Evidence Export Manifest

## Plan Review

- Session: `batch-7a-2-evidence-manifest`
- Final phase: plan verification
- Final verdict: `green`
- Green light: `yes`
- Minimum score: 9

Claude initially challenged the 7A.2 plan on manifest ownership, schema-version scope, and avoiding accidental retention/provenance expansion. Codex accepted the useful constraints and narrowed the plan:

- Manifest models live in a narrow evidence export contract module, not in the router or full renderer.
- `flow_run_export_json.py` remains the JSON export renderer and manifest builder.
- 7A.2 adds only the current provenance schema version constant needed for export v3; strict parser/corruption behavior stays in 7A.3.
- Retention and artifact availability fields are truth-telling current-state summaries, not fake tombstone/file-row implementations.
- No evidence ledger, raw payload retention, migration, frontend evidence UI work, package rename, or namespace migration starts in this slice.

## Implementation Review Iteration 1

- Session: `batch-7a-2-evidence-manifest-implementation`
- Phase: implementation
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: 7

Accepted findings:

- Add HTTP-level hash verification so the served attachment bundle, after response-model validation, matches `content_hash`.
- Remove the impossible-state bundle/context guard.
- Make manifest `flow_version` non-null and use required-key access.
- Remove redundant service casts around the renderer return.
- Inline the one-line artifact count helper.

Codex changes:

- Added an integration assertion that re-hashes `payload["bundle"]` from the actual HTTP attachment.
- Kept `FlowRunEvidenceExportResponse.manifest` typed while making `bundle` open JSON so response validation cannot strip hashed evidence fields.
- Removed `_validate_export_context_matches_bundle`.
- Changed `EvidenceExportManifest.flow_version` to `int` and read `run["flow_version"]`.
- Removed the service-level `cast(dict[str, Any], ...)` wrappers.
- Inlined the artifact count extraction.

## Implementation Review Iteration 2

- Session: `batch-7a-2-evidence-manifest-implementation`
- Phase: verification
- Verdict: `changes_required`
- Green light: `no`
- Minimum score: 7

Accepted findings:

- The checked-in generated TypeScript schema still exposed `EvidenceExportManifest.flow_version` as `number | null`.
- OpenAPI tests did not assert non-null flow-version schema.
- `EvidenceExportContext` also uses `extra="forbid"` and needed symmetric strict-extra coverage.
- The intentionally open export `bundle` field needed an in-place reason to prevent future re-tightening that would break hash semantics.

Codex changes:

- Updated `frontend/packages/intric-js/src/types/schema.d.ts` so manifest `flow_version` is `number`.
- Added OpenAPI assertions that manifest `flow_version` is an integer, not nullable, and not `anyOf`.
- Added OpenAPI assertions that export `bundle` remains an open object.
- Added `test_evidence_export_context_rejects_unknown_fields`.
- Added a concise field description explaining why the export bundle remains open JSON.

## Implementation Review Iteration 3

- Session: `batch-7a-2-evidence-manifest-implementation`
- Phase: verification
- Verdict: `green`
- Green light: `yes`
- Minimum score: 8

Claude verified the accepted findings were resolved. No accepted or partial findings remain for this slice.

Non-blocking carry-forward:

- Add a raw-detail HTTP re-hash pin in a future slice if the export router/renderer is touched again.
- Type the top-level `summary` and `redaction` bags in a later evidence export tightening pass.
- Schedule a scoped generated-schema regeneration before any external SDK release.
- Consider removing top-level `schema_version`, `generated_at`, and `content_hash` mirrors before publication.

## Local Verification After Reconciliation

- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail -q`: 19 passed.
- `cd backend && uv run pytest tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py -q`: 40 passed.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_returns_json_attachment tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_passes_raw_detail_and_reason tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_rejects_raw_invalid_reason -q`: 4 passed.
- `cd backend && uv run pyright ...`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 11 files already formatted.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- `cd frontend/packages/intric-js && bun run check`: passed.
- `cd frontend/packages/intric-js && bun run lint`: passed.
- Anti-slippage `rg` for stale v2 schema, untyped manifest, and internal planning vocabulary across touched source/test/generated schema paths: no matches.
- `git diff --check -- ...`: passed.

Docker/devcontainer note:

- `docker exec eneo-41ae93-eneo-1 ...` was attempted after explicit user permission, but the local Codex tool policy rejected Docker execution before the command reached Docker: `approval required by policy, but AskForApproval is set to Never`.
