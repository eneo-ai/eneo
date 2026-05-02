# Batch 7A — Evidence / Provenance Contract Foundation Journal

## Iteration 1 — 7A.1 Plan

### Repository Gate

- `git rev-parse --short HEAD`: `2ae78ddd`
- Latest commit: `2ae78ddd flows: centralize active step selection`
- `git status --short --branch`: only the known unrelated dirty files were present:
  - `frontend/packages/ui/src/icons/types.d.ts`
  - `scripts/run_codex_review.sh`
  - `PRODUCT.md`
- `git diff --cached --name-only`: empty
- Batch 8 had not started.

### Docker Status

`docker ps --format '{{.Names}}'` was attempted and blocked by host policy:

```text
Rejected("approval required by policy, but AskForApproval is set to Never")
```

Use local fallback validation for this slice unless Docker becomes available without elevated approval.

### Read Inputs

- `AGENTS.md`
- `docs/refactor/implementation-order.md`
- `docs/refactor/execution/loop-protocol.md`
- `docs/refactor/execution/retrospective-checklist.md`
- `docs/refactor/execution/implementation-bootstrap.md`
- `docs/refactor/prd/PRD-003-runtime-reliability-and-feature-gaps.md`
- `docs/refactor/prd/PRD-004-api-consumer-and-api-maintainer-dx.md`
- `docs/refactor/prd/PRD-006-frontend-single-source-of-truth.md`
- `docs/refactor/prd/PRD-007-testing-strategy.md`
- `docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md`
- `docs/refactor/prd/PRD-009-observability-and-operability.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`
- `docs/engineering/frontend-state-standard.md`
- `docs/engineering/comment-and-readability-standard.md`
- latest Batch 7 journal, retrospective, and Claude reconciliation

### Initial Evidence Inventory

- Evidence HTTP adapter: `backend/src/intric/flows/api/flow_run_evidence_router.py:65` and `backend/src/intric/flows/api/flow_run_evidence_router.py:137`
- Export JSON renderer: `backend/src/intric/flows/flow_run_export_json.py:60`
- Loose export manifest: `backend/src/intric/flows/flow_run_export_json.py:114`
- Evidence bundle builder/redactor: `backend/src/intric/flows/flow_run_evidence_bundle.py:62` and `backend/src/intric/flows/flow_run_evidence_bundle.py:83`
- Attempt provenance model: `backend/src/intric/flows/flow_run_provenance.py:82`
- Attempt provenance persistence: `backend/src/intric/database/tables/flow_tables.py:568`
- Attempt provenance writer: `backend/src/intric/flows/runtime/executor.py:177`
- Result-row tool-call duplicate: `backend/src/intric/database/tables/flow_tables.py:499`, `backend/src/intric/flows/infrastructure/flow_repo.py:542`
- Attempt-scoped result file owner: `backend/src/intric/database/tables/flow_tables.py:680`
- Retention cleanup without tombstones: `backend/src/intric/data_retention/infrastructure/data_retention_service.py:387` and `backend/src/intric/data_retention/infrastructure/data_retention_service.py:458`
- Frontend evidence parser/view-model candidate: `frontend/apps/web/src/lib/features/flows/flowEvidenceProvenance.ts:20`
- Frontend Svelte bundle parsing candidate: `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:40`

### Plan Decision

7A.1 stays deliberately narrow:

- strengthen public evidence export pins
- delete only the unsupported-format branch that the public `Literal["json"]` API already makes unreachable
- require an explicit raw export reason before export/audit
- record all larger evidence work as carry-forward 7A slices

No migration, new evidence ledger, raw payload retention, frontend rewrite, rerun, review pause/resume, package rename, or namespace rename is in scope.

### Claude Plan Review 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted findings:

- Unsupported-format deletion was under-scoped. The error also appeared in OpenAPI startup tests and generated-client-sensitive schema docs.
- Raw export reason behavior needed a clear policy. Repo grep showed current frontend/package callers use redacted export without a reason, while raw export callers were tests/service paths. Decision: keep redacted default `support_debug`; reject raw exports that omit a specific reason or inherit the generic default.
- Export audit fail-closed behavior should get an integration-level pin, not only a unit-level pin.
- Current manifest keys/types should be pinned before 7A.2 changes the manifest into a typed model.
- Tool-call metadata and JSON artifact scanning need current caller inventories now so 7A.4/7A.6 do not rediscover or miss destructive readers.

Rejected/Deferred findings:

- Regenerating the whole generated client is deferred. This slice may update the narrow generated schema comment for the changed 400 response if needed, but no broad generated churn or package rename is in scope.
- Retention tombstone tests are deferred because a tombstone store is a schema/data-model decision and belongs to 7A.5.

Plan revisions:

- Added `backend/tests/unit/test_server_startup_imports.py` and `frontend/packages/intric-js/src/types/schema.d.ts` to the deletion/change inventory.
- Added explicit redacted-vs-raw reason policy.
- Added export audit fail-closed integration pin.
- Added manifest key-set pin.
- Added duplicate-owner caller inventories for `tool_calls_metadata` and result JSON artifact scanning.

### Claude Plan Verification 2

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Non-blocking implementation notes accepted before source edits:

- Use one router constant for the redacted default reason and raw-rejection sentinel.
- Pin the exact manifest key set before typed manifest work.
- Treat the narrow `schema.d.ts` update as intentional generated-client-sensitive documentation, with full regeneration verification carried forward to 7A.2.

### Implementation Summary

Changed source/test/generated docs:

- `backend/src/intric/flows/api/flow_run_evidence_router.py`
  - Replaced the never-shipped custom unsupported-format 400 branch with raw export reason validation.
  - Added one default reason constant so the redacted default and raw rejection sentinel cannot drift.
  - Validates malformed raw export reason before run lookup to avoid redundant work and run-existence side effects.
  - Kept the router as the HTTP/audit boundary owner.
- `backend/tests/unit/test_flow_openapi_contract.py`
  - Pinned `format` as JSON-only and documented raw reason requirements.
- `backend/tests/unit/test_server_startup_imports.py`
  - Retargeted the evidence export 400 example from the deleted format error to the raw-reason error.
- `backend/tests/unittests/flows/test_flow_router.py`
  - Deleted the direct-function unsupported-format test.
  - Added raw default-reason rejection coverage.
  - Added raw blank-after-strip reason coverage.
  - Pinned redacted default audit metadata and raw explicit audit metadata.
  - Normalized touched debug export fixtures to v2.
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
  - Pinned current manifest key set before 7A.2 typed manifest migration.
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
  - Added export audit fail-closed integration coverage.
- `frontend/packages/intric-js/src/types/schema.d.ts`
  - Updated the checked-in generated schema comments for the changed evidence export 400 response and reason parameter description.

### Validation Summary

- `cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_returns_json_attachment tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_passes_raw_detail_and_reason tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_fails_closed_when_audit_write_fails tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_rejects_raw_invalid_reason tests/integration/flows/test_flow_evidence_api_contracts.py -q`: 49 passed.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_returns_hashed_redacted_bundle -q`: 17 passed.
- `cd backend && uv run pyright src/intric/flows/api/flow_run_evidence_router.py tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py tests/unittests/flows/test_flow_router.py tests/unittests/flows/test_flow_run_evidence.py tests/integration/flows/test_flow_evidence_api_contracts.py`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 6 files already formatted.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- Anti-slippage `rg` for deleted unsupported-format code, raw default leakage, debug-export v1 fixtures, and internal planning vocabulary across touched source/test/generated schema paths: no matches.
- `git diff --check -- ...`: passed.
- `cd frontend/packages/intric-js && bun run check`: passed.
- `cd frontend/packages/intric-js && bun run lint`: passed.
- OpenAPI runtime dump check: `flow_evidence_export_format_not_supported` absent; evidence export 400 example is `flow_evidence_export_reason_required`.

Warnings observed were existing deprecation warnings from Pydantic/Starlette imports and are not product regressions.

### Carry-Forward Risks

- 7A.2 must replace the loose manifest with a typed export manifest and explicitly verify/regenerate `intric-js` schema output for the hand-updated evidence export 400 example.
- Unsupported `format` values now rely on FastAPI's `Literal["json"]` request validation rather than a Flow-specific typed 400; if public SDK ergonomics require a typed invalid-format error later, handle it as an API-contract design decision.
- Redacted exports still allow the default `support_debug` reason for existing redacted caller ergonomics; later compliance hardening may require a UI/API decision to collect explicit redacted export reasons too.
- 7A.3 still owns attempt provenance schema versioning, strict parser behavior, and corruption markers.
- 7A.4 still owns `tool_calls_metadata` single-source normalization and RAG truthfulness states.
- 7A.5 still owns retention tombstones/deletion semantics and likely requires an explicit migration/data-model decision.
- 7A.6 still owns artifact/file evidence canonicalization through `FlowRunStepResultFiles` + `Files`.
- 7A.7 still owns frontend evidence generated aliases/view model alignment if backend evidence schemas change.

## Iteration 2 — 7A.2 Typed Manifest

### Plan Review Result

Claude plan review session: `batch-7a-2-evidence-manifest`.

- Iteration 1: `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.
- Iteration 2: `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.
- Iteration 3: `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 9`.

Accepted plan findings:

- The manifest must be canonical for `schema_version` and `content_hash`; top-level envelope fields remain only as tested mirrors.
- `audit_event_id` is deferred until the audit service exposes a real durable audit row id. This slice does not ship a permanent-null API field.
- The typed manifest model lives in the narrow `flow_run_evidence_export_manifest.py` leaf module, not in API models or the full renderer.
- Renderer input is one `EvidenceExportContext` value object, not loose kwargs.
- `redaction_applied` and `masked_fields_count` stay in the manifest because 7A.1 pinned them as the migration target; they mirror the detailed top-level `redaction` block and are equality-tested.
- `provenance_persisted_version_status` and retention tracking states are forward-compatible so later provenance/retention slices do not require a schema bump just to widen emitted states.
- Runtime note strings must not mention internal batch/plan labels.

### Implementation Summary

Changed source/test/generated schema:

- `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
  - Added strict typed export manifest and export context models.
  - Added truth-telling retention and artifact availability summaries with additive future-extension room.
- `backend/src/intric/flows/flow_run_export_json.py`
  - Bumped evidence export schema to `flow-evidence-export.v3`.
  - Builds the manifest through `EvidenceExportManifest`.
  - Hashes the exact returned `bundle` payload and records `content_hash_input`.
  - Keeps top-level `schema_version`, `generated_at`, and `content_hash` as envelope mirrors.
- `backend/src/intric/flows/flow_run_provenance.py`
  - Added `FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION` and default `schema_version` on normalized attempt provenance payloads.
  - Strict parser and corruption behavior remain 7A.3.
- `backend/src/intric/flows/application/flow_run_service.py`
  - Passes `EvidenceExportContext` into the renderer.
- `backend/src/intric/flows/api/flow_run_evidence_router.py`
  - Passes the already-validated export reason into the service.
- `backend/src/intric/flows/api/flow_models.py`
  - Changes the public export response manifest from `dict[str, Any]` to `EvidenceExportManifest`.
  - Keeps the export attachment `bundle` as open JSON so response validation cannot strip evidence fields after the content hash is computed.
- `backend/.importlinter`
  - Adds the new manifest module to the Flow engine boundary contract.
- `frontend/packages/intric-js/src/types/schema.d.ts`
  - Updates the generated-client-sensitive schema surface with typed manifest components, `flow-evidence-export.v3`, and the open evidence export bundle object.
- `frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts`
  - Updates package-local type-smoke coverage so the generated evidence export alias must satisfy the new manifest while the normal evidence read model remains typed separately.

### Schema Version Bump

The export schema changes from `flow-evidence-export.v2` to `flow-evidence-export.v3`.

Rationale:

- The manifest is no longer a loose bag; it is a typed public contract with explicit hash semantics and provenance/export metadata.
- Raw and redacted exports now declare whether the content hash covered the raw or redacted returned bundle.
- This Flow evidence surface is still pre-production and has no released external SDK contract on this branch.

Field-level manifest changes:

- Added: `schema_version`, `provenance_schema_version_min`, `provenance_schema_version_current`, `provenance_persisted_version_status`, `content_hash_input`, `exported_at`, `tenant_id`, `exported_by_user_id`, `export_reason`, `detail_mode`, `retention_state_summary`, `artifact_availability_summary`.
- Kept from 7A.1 manifest pin: `run_id`, `flow_id`, `trace_id`, `flow_version`, `content_hash`, `redaction_applied`, `masked_fields_count`, `redaction_policy_version`.
- Deferred: `audit_event_id`, historical provenance row verdicts, retention tombstones, and canonical file-row artifact availability.
- Export response `bundle` remains an open evidence object by design. The strongly typed `FlowRunEvidenceResponse` remains the read-model contract, while the downloadable export must preserve the exact bundle covered by `content_hash`.

Source verification:

- `FlowRun.flow_version` is non-null in the domain model and database table: `backend/src/intric/flows/domain/flow.py:132`, `backend/src/intric/database/tables/flow_tables.py:334`.
- `FlowRun.trace_id` is non-null in the domain model and database table: `backend/src/intric/flows/domain/flow.py:138`, `backend/src/intric/database/tables/flow_tables.py:357`.
- Grep for `trace_id`/`flow_version` `None` in Flow source/tests found optional request/response fields and expected-flow-version inputs, but no FlowRun persistence fixture with null `trace_id` or `flow_version`.

### Validation Summary

- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail -q`: 19 passed.
- `cd backend && uv run pytest tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py -q`: 40 passed. The integration export test re-hashes the actual served attachment bundle.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_returns_json_attachment tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_passes_raw_detail_and_reason tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_rejects_raw_invalid_reason -q`: 4 passed.
- `cd backend && uv run pyright ...`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 11 files already formatted after applying ruff format to touched files.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- `cd frontend/packages/intric-js && bun run check`: passed.
- `cd frontend/packages/intric-js && bun run lint`: passed.
- Anti-slippage `rg` for stale v2 schema, untyped manifest, and internal planning vocabulary across touched source/test/generated schema paths: no matches.
- `git diff --check -- ...`: passed.
- `docker exec eneo-41ae93-eneo-1 ...`: blocked before Docker execution by the local tool approval policy (`AskForApproval is set to Never`); local/testcontainers validation above passed.

Warnings observed were existing deprecation warnings and not product regressions.

### Claude Implementation Review Fixes

Implementation review session: `batch-7a-2-evidence-manifest-implementation`.

Iteration 1 returned `changes_required` with one accepted medium finding and several accepted low findings.

Accepted fixes applied:

- Added an HTTP-level integrity assertion that re-hashes the served attachment `payload["bundle"]`.
- Kept the export response manifest typed while making the export `bundle` open JSON so response validation cannot alter the hashed object.
- Removed the impossible-state bundle/context validation guard.
- Made manifest `flow_version` non-null and read it by required key.
- Removed redundant service casts around `render_evidence_json_export`.
- Inlined the one-line artifact count helper.
- Aligned the generated TypeScript schema with the non-null manifest `flow_version`.
- Added OpenAPI assertions for non-null `flow_version` and open export `bundle` shape.
- Added strict-extra coverage for `EvidenceExportContext`.
- Documented the intentionally open export bundle field in the API response model.

Accepted carry-forward:

- `summary` and `redaction` remain open JSON in this slice. They are existing export summary/detail surfaces and can be typed in a later evidence export tightening pass without weakening the v3 manifest.

Iteration 3 verification returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. Reconciliation is recorded in `claude-reconciliation-3.md`.

### Carry-Forward Risks

- 7A.3 must implement strict provenance parser behavior, historical/corrupt markers, and per-attempt persisted provenance version status.
- 7A.5 must replace the current retention `not_tracked` summary with tombstone-backed counts and deletion semantics.
- 7A.6 must replace payload-derived artifact availability with `FlowRunStepResultFiles` + `Files` canonical availability.
- `audit_event_id` remains deferred until the audit layer can provide a real durable id; do not add a permanent-null API field.
- The top-level export envelope still mirrors manifest `schema_version`, `generated_at`, and `content_hash` for response compatibility. Equality tests guard drift, but later cleanup may decide whether to remove these mirrors before publication.

## Iteration 3 — 7A.3 Provenance Versioning

### Plan

Active slice: provenance schema version and corruption behavior.

Planned source ownership:

- `flow_run_provenance.py` owns attempt provenance schema/version parsing and corruption markers.
- `flow_run_evidence_bundle.py` owns persisted attempt row normalization for raw and redacted evidence bundles.
- `flow_run_export_json.py` owns the export-manifest summary of persisted provenance version status.

No historical reader is planned because no persisted row-count proof is available in this environment and Flow/Flow AI Builder are pre-production on this branch. Unversioned branch-local fixtures are test data to update or explicit corruption-marker cases, not shipped compatibility evidence.

### Claude Plan Review 1

Claude returned `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted plan changes:

- Runtime writer must round-trip through `FlowAttemptProvenance` before persistence so new writer sections cannot drift from the strict reader.
- Corruption marker schema is a strict Pydantic model with distinct literal `flow-attempt-provenance-marker.v1`.
- Bundle normalization must produce typed provenance parse results that both the serialized bundle and manifest summary consume.
- Raw and redacted bundles must share the same attempt normalization mechanism through `EvidenceBundlePayload`.
- HTTP-level corrupt-manifest status coverage is required, not optional.
- Mixed valid-v1 and no-provenance attempts report manifest status `tracked`; per-attempt payloads carry the precise state.

### Claude Plan Review 2

Claude returned `changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 8`.

Accepted plan fixes:

- Removed the canonical corruption marker literal from the negative anti-slippage grep so the guard will not fail on the source constant it requires.
- Pinned the marker landing surface: corruption markers replace `step_attempts[i].provenance_json` only inside the export bundle, while the typed evidence read-model contract remains unchanged in this slice.
- Pinned the bundle plumbing: raw and redacted evidence bundles expose `to_export_payload()` returning `EvidenceBundlePayload`; `to_dict()` remains payload-only.

Claude's remaining feedback was mechanical plan hygiene rather than a design change. No source implementation has started.

### Claude Plan Review 3

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Implementation guardrails carried forward:

- The writer round-trip test should cover every section that used to be appended after `FlowAttemptProvenance.to_payload()`.
- Corruption marker fixtures should cover non-dict, missing schema, unsupported schema, and unknown top-level keys.
- HTTP export corruption coverage should assert both manifest status and bundle marker.
- `EvidenceBundlePayload` must be the in-process handoff; the manifest must not infer status by scanning serialized marker bytes.

### Implementation Summary

Changed source/tests:

- `backend/src/intric/flows/flow_run_provenance.py`
  - Added strict current-schema parsing around `flow-attempt-provenance.v1`.
  - Added typed corruption markers with distinct marker schema `flow-attempt-provenance-marker.v1`.
  - Kept `normalize_attempt_provenance` as the canonical current-provenance normalizer for callers that only accept valid current payloads.
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
  - Added `EvidenceBundlePayload` as the raw/redacted export handoff carrying both serialized payload and typed provenance parse results.
  - Routes raw and redacted attempt serialization through the same parser/marker path.
- `backend/src/intric/flows/flow_run_export_json.py`
  - Computes `provenance_persisted_version_status` from typed parse results instead of serialized marker scanning.
- `backend/src/intric/flows/runtime/executor.py`
  - Builds complete attempt provenance payloads before validating through `FlowAttemptProvenance`.
  - Removes post-`to_payload()` mutation as a drift source.
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
  - Pins valid current provenance parsing, corruption markers, raw/redacted marker parity, and manifest status rules.
- `backend/tests/unittests/flows/test_step_attempt_runtime.py`
  - Pins runtime writer round-trip behavior across LLM, RAG, runtime input, transcription, guards, template, artifacts, HTTP, and citations.
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
  - Pins HTTP evidence export status/marker behavior for corrupt persisted attempt provenance.

No historical reader shipped. Unversioned branch-local fixtures were updated to v1 unless they intentionally exercise corruption behavior.

### Validation Summary

- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_step_attempt_runtime.py -q`: 36 passed before the final invariant addition.
- `cd backend && uv run pytest tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance -q`: 2 passed.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail tests/unittests/flows/test_step_attempt_runtime.py tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py -q`: 78 passed.
- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_step_attempt_runtime.py tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance -q`: 38 passed after adding parse-result invariants.
- `cd backend && uv run pyright ...`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 7 files already formatted.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- Anti-slippage `rg` for stale provenance/version/internal planning vocabulary across touched source/test files: no matches.
- `git diff --check -- ...`: passed.
- `docker ps --format '{{.Names}}'`: blocked before Docker execution by the local Codex approval policy (`AskForApproval is set to Never`); local/testcontainers validation above passed.

Warnings observed were existing deprecation warnings and not product regressions.

### Carry-Forward Risks

- 7A.4 still owns tool-call single-source normalization and RAG truthfulness states.
- 7A.5 still owns retention tombstones, deletion semantics, and availability markers.
- 7A.6 still owns artifact/file evidence ownership through `FlowRunStepResultFiles` + `Files`.
- 7A.7 still owns frontend evidence generated aliases/view-model alignment if backend evidence schemas change.
- No durable historical reader exists because no persisted historical row proof is available; if future data inspection proves historical rows, add a named reader with owner, row proof, deletion condition, and tests.

### Claude Implementation Review 1

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 7`, with non-blocking accepted cleanup findings.

Fixes applied before verification:

- Split persisted provenance parsing from export enrichment with `_enrich_attempt_provenance_for_export`.
- Removed the no-op parse-result reassignment and stopped mutating the parse result's provenance object.
- Returned the dumped attempt dict directly instead of rebuilding a shallow copy.
- Reduced corruption marker noise by emitting `unknown_keys` and `raw_value_type` only when they add information.
- Changed runtime writer assembly to pass `LlmProvenance` into the final `FlowAttemptProvenance` validation instead of dumping then re-validating that section.
- Added a writer/parser handshake assertion: `_build_attempt_provenance` output must parse as `tracked`.
- Added current-schema validation-failure coverage for malformed `llm.effective_prompt`.
- Added a writer-side known-LLM-key assertion as the bounded guard for the deliberately additive nested provenance models.

Deliberate carry-forward:

- Nested provenance sections remain additive in 7A.3 because the plan explicitly keeps nested `extra="allow"` for forward-compatible metadata. 7A.4-7A.6 can tighten specific sections when tool-call, RAG, and artifact ownership become canonical.
- Raw `EvidenceBundle.to_export_payload()` remains computed on demand. Current export rendering calls it once; caching parse results would add another state copy inside the bundle object without a measured need.

### Claude Implementation Review 2-3

- Iteration 2 returned a green textual verdict, but the wrapper did not parse the markdown-headed `GREEN_LIGHT` line and exited nonzero.
- Iteration 3 reran the same session with the exact output contract and returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.
- Claude confirmed no accepted or partial findings remain.

### Final Validation Summary

- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail tests/unittests/flows/test_step_attempt_runtime.py tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance tests/unit/test_flow_openapi_contract.py tests/unit/test_server_startup_imports.py -q`: 79 passed.
- `cd backend && uv run pyright ...`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 7 files already formatted.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- Anti-slippage `rg` across touched source/test files: no matches.
- `git diff --check -- ...`: passed.

## Iteration 5 — 7A.4 Evidence Single-Source Normalization

### Plan Draft

The active 7A.4 plan narrows the slice to evidence single-source normalization:

- attempt provenance becomes the export source of truth for tool-call evidence
- runtime completed results stop copying tool calls into `FlowStepResult.tool_calls_metadata`
- evidence bundles omit result-level tool calls, including for old branch-local result rows
- RAG summary states distinguish `not_tracked`, `tracked_no_sources`, `tracked_with_sources`, and `unknown_corrupt`
- no migration, table/column deletion, frontend evidence view rewrite, Batch 8 rerun work, or Batch 9 review work starts in this slice

### Claude Plan Review 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted findings and plan fixes:

- The initial single-source claim was too broad because `FlowRunStepPublic.tool_calls_metadata`, the DB column, repository persistence slot, generated schema, and public API tests still exist. The plan now calls this boundary asymmetry out explicitly: write-side and evidence-export paths migrate in 7A.4, while persisted/public readers remain Tier B and are marked deprecated.
- RAG state aggregation was under-specified. The plan now defines precedence: `unknown_corrupt` over `tracked_with_sources` over `tracked_no_sources` over `not_tracked`.
- Corrupt provenance markers would be invisible to a payload-only `_collect_rag_tracking` helper. The plan now requires the summary helper to consume typed `FlowAttemptProvenanceParseResult` values from `EvidenceBundlePayload`.
- `tool_calls_metadata` export shape was ambiguous. The plan now chooses absence from evidence bundle step-result payloads and requires a test for the key contract.
- `default_rag_tracking()` remains the per-attempt default for real RAG sections only. Export fallback uses a distinct untracked summary.
- The surviving public result field will be marked deprecated in `FlowRunStepPublic`, with an OpenAPI assertion so generated-client consumers get a signal.
- Data-retention cleanup was audited: `data_retention_service.py` still updates rows when non-tool debug fields are present or output payload pruning changes the payload, so no retention cleanup source change is planned.
- The anti-slippage grep was corrected so it does not fail on the new truthful RAG note.

Source implementation remained paused during this plan review.

### Claude Plan Review 2

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Final plan tightenings applied before implementation:

- Changed the stale inventory wording from "omit or null" to "omit" for `bundle.step_results[*].tool_calls_metadata`.
- Pinned helper names: `derive_rag_usage_tracking()` for run-level RAG summary aggregation and `untracked_rag_summary()` for the no-provenance fallback.
- Removed the conditional source-file hedge for `flow_run_provenance.py`; the summary helper belongs in `flow_run_export_json.py` because it consumes export bundle payload and parse results.
- Enumerated the required precedence matrix tests and the old-row tool-call export regression.
- Added a carry-forward deletion trigger for `FlowRunStepPublic.tool_calls_metadata` and the database column: remove only after human-approved SDK/frontend reader audit and persisted-row proof or migration/backfill plan.

### Implementation Summary

Changed source/tests:

- `backend/src/intric/flows/runtime/step_result_builder.py`
  - New completed runtime step results no longer copy `StepExecutionOutput.tool_calls_metadata` into `FlowStepResult.tool_calls_metadata`.
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
  - Evidence bundle step-result serialization omits `tool_calls_metadata`, including for old branch-local rows that still have the field populated.
- `backend/src/intric/flows/flow_run_export_json.py`
  - Added `derive_rag_usage_tracking()` and `untracked_rag_summary()`.
  - RAG summary state now derives from typed provenance parse results plus bundle source details, with precedence `unknown_corrupt/partial_corrupt > tracked_with_sources > tracked_no_sources > not_tracked`.
- `backend/src/intric/flows/api/flow_models.py`
  - Marked `FlowRunStepPublic.tool_calls_metadata` deprecated and pointed evidence consumers to attempt provenance.
- `backend/tests/unittests/flows/test_flow_runtime_builders.py`
  - Pins that completed results do not carry result-level tool-call metadata.
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
  - Pins RAG state precedence and the old-row tool-call export contract.
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
  - Pins tracked-with-sources state through the HTTP evidence export path.
- `backend/tests/unit/test_flow_openapi_contract.py`
  - Pins the OpenAPI deprecation signal for the surviving public read-model field.

No migration, frontend evidence UI change, Batch 8 rerun work, Batch 9 review work, package rename, or namespace rename started.

### Validation Summary

- `cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_runtime_builders.py tests/unittests/flows/test_step_attempt_runtime.py tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance tests/unit/test_flow_openapi_contract.py -q`: 82 passed.
- `cd backend && uv run pyright src/intric/flows/runtime/step_result_builder.py src/intric/flows/api/flow_models.py src/intric/flows/flow_run_evidence_bundle.py src/intric/flows/flow_run_export_json.py tests/unittests/flows/test_flow_runtime_builders.py tests/unittests/flows/test_flow_run_evidence.py tests/integration/flows/test_flow_evidence_api_contracts.py tests/unit/test_flow_openapi_contract.py`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 9 files already formatted after formatting the files ruff identified.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- Anti-slippage `rg` across touched source/test files: no matches.
- `git diff --check -- ...`: passed.
- `docker ps --format '{{.Names}}'`: blocked before Docker execution by the local Codex approval policy (`AskForApproval is set to Never`); local/testcontainers validation above passed.

Warnings observed were existing deprecation warnings and not product regressions.

### Carry-Forward Risks

- `FlowRunStepPublic.tool_calls_metadata`, `FlowStepResult.tool_calls_metadata`, the repository persistence slot, generated schema field, and database column remain as deprecated/Tier B persisted-public surfaces. Delete only after human-approved SDK/frontend reader audit plus persisted-row proof or migration/backfill plan.
- Run-level `partial_corrupt` now separates mixed valid/corrupt RAG evidence from all-corrupt `unknown_corrupt`. Per-attempt detail remains visible in `bundle.step_attempts[*].provenance_json`.
- 7A.5 still owns retention tombstones, deletion semantics, and availability markers.
- 7A.6 still owns artifact/file evidence ownership through `FlowRunStepResultFiles` + `Files`.
- 7A.7 still owns frontend evidence generated aliases/view-model alignment if backend evidence schemas change.

### Claude Implementation Review 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted fixes:

- Added HTTP boundary coverage that corrupt attempt provenance produces `summary.rag_usage_tracking.tracking_state == "unknown_corrupt"` and `retrieval_tracked is False`.
- Added pure-corrupt unit coverage for `unknown_corrupt` with no retrieved sources.
- Replaced the mixed corrupt-plus-valid-source run state with `partial_corrupt`, so `unknown_corrupt` no longer coexists with non-empty RAG source lists.
- Added a runtime handshake test proving the same `StepExecutionOutput.tool_calls_metadata` value omitted from `FlowStepResult` lands in attempt provenance.
- Removed the redundant local variable in `_merge_tracked_rag_summaries` and made `selection_basis` / `note` deterministic by keeping the first tracked summary's values.

Deferred deliberately:

- Dedicated typed export models for `FlowStepResult` bundle payloads are deferred to 7A.6, where artifact/file evidence ownership may add more bundle-only fields.
- Runtime warning behavior for the deprecated API field is deferred to the public API/SDK deletion pass; this slice pins the OpenAPI/generated-client signal.

### Claude Implementation Review 2

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Claude confirmed the accepted findings were resolved:

- HTTP corrupt RAG state is pinned.
- Pure-corrupt and mixed-valid/corrupt RAG state branches are pinned.
- `partial_corrupt` removes the previous `unknown_corrupt` plus source-list ambiguity.
- Runtime tool-call evidence is positively pinned through the result/provenance handshake.
- RAG tracking summary merge no longer has the redundant reassignment or last-write-wins behavior for `selection_basis` / `note`.

Additional verification after Claude green:

- `rg -n "tool_calls_metadata|rag_usage_tracking|tracking_state|unknown_corrupt|partial_corrupt" frontend/apps/web/src/lib/features/flows frontend/packages/intric-js/src`: no Flow UI readers for the deprecated tool-call field or new corrupt states; matches remain in generated/type package files.
- `cd frontend/packages/intric-js && bun run check`: passed.

Carry-forward added:

- `frontend/packages/intric-js/src/types/schema.d.ts` remains generated-client drift for evidence tracking examples/types and the new OpenAPI deprecation marker. Do not hand-edit generated output in this backend slice; 7A.7 owns generated/frontend evidence type alignment if the backend evidence schema changes are kept.

## Iteration 6 — 7A.5 Retention Tombstones And Deletion Semantics

The active 7A.5 plan narrows the slice to retention tombstones and deletion semantics:

- destructive debug/artifact cleanup should write reviewable tombstones instead of silently erasing provenance/artifact evidence
- exact raw prompt/completion byte retention remains out of scope and rejected until a deletion/DSAR contract exists
- existing owners are used first: `FlowStepAttempts.provenance_json`, `FlowStepResults.output_payload_json`, `Files`, and current evidence export/read-model code
- no migration, broad evidence ledger, frontend evidence UI rewrite, Batch 8 rerun, Batch 9 review, package rename, or namespace rename starts in this slice

Docker/container check remains blocked by the local Codex approval policy before Docker execution; local/testcontainers validation remains the fallback.

### Claude Plan Review 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted findings and plan fixes:

- Attempt retention markers would be misclassified as corrupt by the strict provenance parser. The plan now requires explicit retention marker schema versions, a retention-purged parse status, parser branch, export-payload behavior, and provenance-status precedence.
- `EvidenceProvenancePersistedVersionStatus` was a closed literal without a retention-purged state. The plan now calls out the typed public contract change and defers generated frontend schema alignment to 7A.7 instead of hand-editing generated output in this backend slice.
- Cleanup idempotency was under-specified. The plan now requires no-op behavior for current-version markers and a two-pass cleanup test proving the second run returns zero changed debug/artifact counts.
- Per-row cleanup context was under-specified. The plan now chooses explicit row-level Python updates with selected tenant id, run id, trace id, policy source, cutoff, and cleanup timestamp context, avoiding SQL JSON construction in this slice.
- The missing-artifact reconciler was omitted. The plan now requires preserving tombstones and skipping tombstone-only payloads.
- The output-payload tombstone key was unnamed. The plan now uses the namespaced `flow_retention_tombstones` key and requires an `rg` collision check before implementation.
- Redaction behavior was ambiguous. The plan now keeps tombstone actor/source PII-free and pins redacted-export marker preservation.
- Pre-7A.5 rows already purged to `None` are explicitly documented as carry-forward ambiguity rather than silently treated as proof of never-tracked evidence.

Source implementation remained paused during this plan review.

### Claude Plan Review 2

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Claude agreed the no-migration direction was sound, but required more executable detail before implementation. Accepted fixes:

- Added a required 7A.5 test matrix mirroring the specificity used in previous slices.
- Named the new status literals: `retention_purged` for attempt provenance parse results and manifest persisted-version status; retention summary tracking remains `not_tracked | tracked`.
- Pinned RAG tracking behavior for retention-purged attempts so post-7A.5 purge does not collapse into `not_tracked`.
- Clarified that `redacted_for_deletion_count` remains zero in this slice because tenant/DSAR deletion markers are not implemented.
- Defined tombstone `counts` as typed per-marker counts of logical objects made unavailable, not batch-job row counts.
- Required `data_retention_worker` to be a single source constant.
- Required retention summary `note` to be derived from actual state and counts, not a stale static string.
- Added carry-forward for a future discriminated envelope if more persisted attempt-state schemas are added.

Source implementation remained paused during this plan review.

### Claude Plan Review 3

Claude returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Claude confirmed the substantive plan issues were resolved and left only low-risk implementation-review notes. Additional plan tightenings applied before source work:

- Added an ordered RAG tracking precedence ladder.
- Named `retention_purged_attempt_count` as the purged-attempt context field for mixed tracked/purged RAG summaries.
- Made the HTTP evidence export pin a hard requirement rather than conditional.
- Added an OpenAPI contract pin for the new `retention_purged` manifest status literal.
- Required deterministic retention-summary note derivation.
- Explicitly required `FlowAttemptProvenanceParseResult.to_export_payload()` to return retention marker payloads for `retention_purged`.

The pre-implementation marker collision grep returned no existing source/test writers for `flow_retention_tombstones`, `flow-retention-tombstone`, or `flow-attempt-retention-marker`.

Source implementation proceeded after this green plan review.

### Implementation Summary

Changed source/tests:

- `backend/src/intric/flows/flow_retention_tombstone.py`
  - Added the canonical Flow retention tombstone schema, attempt-retention marker schema, typed per-marker count models, payload-key constant, actor-source constant, and parsing/appending helpers.
- `backend/src/intric/data_retention/infrastructure/data_retention_service.py`
  - Runtime retention now threads tenant/run/trace/cutoff/policy context through cleanup.
  - Debug cleanup writes step-result tombstones and attempt retention markers before clearing sensitive fields.
  - Generated artifact cleanup writes artifact-content tombstones before pruning payload references and clearing `Files` content.
  - Missing-artifact reconciliation preserves tombstones and skips tombstone-only payloads.
- `backend/src/intric/flows/flow_run_provenance.py`
  - Attempt provenance parsing now recognizes `flow-attempt-retention-marker.v1` as `retention_purged` instead of corrupt.
  - Invalid retention markers get the explicit corruption code `flow_attempt_provenance_invalid_retention_marker`.
- `backend/src/intric/flows/flow_run_export_json.py`
  - Manifest retention summary now derives counts from tombstones in evidence bundle payloads.
  - Provenance status precedence is `corrupt > retention_purged > tracked > not_tracked`.
  - RAG tracking now reports retention-purged attempts explicitly and adds `retention_purged_attempt_count` once at the summary boundary.
- `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
  - Manifest status accepts `retention_purged`.
  - Retention summary requires `artifact_content_purged_count`.
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
  - The result-field omission now uses `_RESULT_FIELDS_REPLACED_BY_ATTEMPT_PROVENANCE` instead of an inline exclude set.
- `backend/src/intric/flows/api/flow_models.py`
  - Evidence export example matches the tombstone-aware manifest shape.
  - Removed the public `FlowRunStepPublic.tool_calls_metadata` deprecation surface; Flow/Flow AI Builder are unreleased, so the public compatibility field should not survive these refactors.
- Tests now pin cleanup idempotency, tombstone counts, invalid retention-marker parsing, redacted marker preservation, HTTP corrupt+tombstone precedence, OpenAPI retention status/count fields, and absence of public result-level `tool_calls_metadata`.

No migration, frontend evidence UI change, Batch 8 rerun work, Batch 9 review work, package rename, or namespace rename started.

### Validation Summary

- `cd backend && uv run pytest tests/integration/test_flow_runtime_retention_cleanup.py tests/unittests/flows/test_flow_run_evidence.py tests/unit/test_flow_openapi_contract.py tests/unittests/flows/test_flow_models.py -q`: 88 passed, 16 warnings.
- `cd backend && POSTGRES_HOST=placeholder uv run pytest tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_with_retention_tombstone -q`: 3 passed, 16 warnings.
- `cd backend && uv run pyright ...`: 0 errors.
- `cd backend && uv run ruff check ...`: all checks passed.
- `cd backend && uv run ruff format --check ...`: 13 files already formatted.
- `cd backend && uv run lint-imports --no-cache`: 3 contracts kept, 0 broken.
- `rg -n "flow_retention_tombstones|flow-retention-tombstone|flow-attempt-retention-marker" backend/src backend/tests`: only the new schema constants and one invalid-marker test literal remain.
- Anti-slippage `rg` across touched source/test files: no matches.
- `git diff --check -- ...`: passed.
- `docker ps --format '{{.Names}}'`: blocked before Docker execution by the local Codex approval policy (`AskForApproval is set to Never`); local/testcontainers validation above passed.

Warnings observed were existing deprecation warnings outside Flow evidence and not product regressions.

### Carry-Forward Risks

- Full `tool_calls_metadata` deletion sweep remains and is assigned to the existing PRD-008 / Batch 10 cleanup anchors: `docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md:18` and `docs/refactor/implementation-order.md:25`. Delete these together after Batch 7A finishes the evidence foundation because `backend/src/intric/flows/runtime/executor.py:187-188` still reads runtime output tool calls into attempt provenance:
  - `backend/src/intric/flows/domain/flow.py:170`
  - `backend/src/intric/database/tables/flow_tables.py:499`
  - `backend/src/intric/flows/infrastructure/flow_repo.py:542`
  - `backend/src/intric/flows/runtime/step_result_builder.py:94`
  - `backend/src/intric/flows/runtime/step_execution_runtime.py:795`
  - `backend/src/intric/flows/runtime/step_execution_runtime.py:910`
  - `backend/src/intric/flows/runtime/step_execution_runtime.py:988`
  - `backend/src/intric/flows/runtime/template_fill_runtime.py:238`
  - `backend/src/intric/flows/runtime/models.py:60`
  - `backend/src/intric/flows/flow_run_evidence_bundle.py:21`
  - `backend/src/intric/flows/flow_run_evidence_bundle.py:183`
- `frontend/packages/intric-js/src/types/schema.d.ts` remains generated-client drift for the new retention manifest fields and for the removed public `FlowRunStepPublic.tool_calls_metadata` field. Do not hand-edit generated output in this backend slice; 7A.7 owns generated/frontend evidence type alignment if the backend evidence schema changes are kept.
- Pre-7A.5 rows already purged to `provenance_json=None` or already-pruned output payloads remain indistinguishable from never-tracked evidence until a human-approved migration/backfill exists.
- The tombstone payload approach is intentionally no-migration. If DSAR/tenant deletion markers or a fourth tombstone writer appear, revisit whether the attempt/result owners still suffice or whether a dedicated table earns its existence.

### Claude Implementation Review 1

Claude returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`.

Accepted fixes:

- Added coverage for invalid attempt-retention markers and the explicit `flow_attempt_provenance_invalid_retention_marker` corruption code.
- Replaced the free-form tombstone count dict with typed count models validated against `data_class`, `object_type`, and `retention_state`.
- Made `artifact_content_purged_count` required in the typed manifest summary.
- Changed attempt retention counts from the column-name key `provenance_json` to the logical `cleared_field_count`.
- Collapsed RAG retention count annotation to one summary-boundary assignment.
- Recorded the broader `tool_calls_metadata` deletion sweep as PRD-008 / Batch 10 carry-forward and replaced the inline evidence-bundle exclude set with a named constant.

Rejected or deferred:

- A new retention table remains out of scope for 7A.5; existing owners are sufficient for current evidence.
- Concurrency guards beyond idempotent marker checks are deferred because the retained state is deterministic and the current worker path is not introducing a new duplicate-start surface.

### Claude Implementation Review 2-4

- Iteration 2 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`. Source shape was mostly accepted, but the RAG retention count assignment still had two branch-local writes and the `tool_calls_metadata` cleanup was not recorded with an owning PRD/batch.
- Iteration 3 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 7`. Source findings were closed, but the 7A.5 journal content was nested under the 7A.4 heading and the cleanup carry-forward needed concrete file paths plus a verified PRD-008 / Batch 10 anchor.
- Iteration 4 returned `VERDICT: green`, `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Claude confirmed the accepted findings were resolved:

- RAG `retention_purged_attempt_count` is assigned once at the summary boundary.
- `_RESULT_FIELDS_REPLACED_BY_ATTEMPT_PROVENANCE` replaces the inline evidence-bundle exclude set.
- 7A.5 journal content lives under one coherent iteration heading with chronological plan reviews, implementation summary, validation summary, carry-forward risks, and implementation review.
- The `tool_calls_metadata` deletion sweep lists concrete file paths and links to existing PRD-008 / Batch 10 anchors.
- Source has no AI slop comments, process/tooling vocabulary, or new deprecated/legacy/backward-compatibility surface for unreleased Flow / Flow AI Builder.
