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
