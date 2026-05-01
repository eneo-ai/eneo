# Batch 7A — Evidence / Provenance Contract Foundation

## Active Next Plan

The active implementation slice is **7A.3 — Provenance schema version and corruption behavior**.

Official Batch 8 step rerun does not start until this inserted evidence/provenance foundation reaches a stable checkpoint. 7A.1 is committed at `5563bb71` and 7A.2 is committed at `d3228d83`. 7A.3 now makes attempt provenance parsing explicit: current provenance parses as `flow-attempt-provenance.v1`, missing/unknown/corrupt provenance produces visible export markers, and export manifests report whether persisted attempt provenance was tracked or corrupt.

## Scope For 7A.3

### Goals

- Make `FlowAttemptProvenance` parsing schema-version-aware before later rerun/review lineage depends on attempt provenance.
- Keep `flow_run_provenance.py` as the canonical owner for attempt provenance schemas, parser decisions, and corruption markers.
- Keep `flow_run_evidence_bundle.py` as the owner that normalizes persisted attempt rows into exportable bundle records.
- Keep `flow_run_export_json.py` as the export-manifest owner that summarizes persisted provenance version status.
- Keep the runtime writer and parser in lockstep: runtime-emitted provenance must round-trip through `FlowAttemptProvenance.model_validate(...).model_dump(mode="json", exclude_none=True)` before persistence.
- Do not add a historical reader without row-count proof or a concrete persisted-data reason.
- Do not silently coerce corrupted or unversioned provenance into current provenance.
- Keep exports available when one attempt has corrupt provenance; the corruption is visible in the affected attempt and in the manifest.

### Non-Goals

- No migration or data backfill.
- No new evidence ledger, provenance table, or historical reader registry unless actual persisted rows prove a need.
- No raw prompt/completion retention.
- No tool-call single-source deletion; 7A.4 owns tool calls and RAG truthfulness.
- No retention tombstones; 7A.5 owns tombstone storage and deletion semantics.
- No artifact/file ownership migration; 7A.6 owns `FlowRunStepResultFiles` + `Files` canonical export.
- No frontend evidence UI/view-model rewrite; 7A.7 owns frontend evidence alignment if backend schemas change.
- No Batch 8 rerun behavior, Batch 9 human review behavior, package rename, or `intric.*` namespace migration.

### Canonical Owner Decisions

| Concept | Current locations | Problem | Canonical home for 7A.3 | Decision |
|---|---|---|---|---|
| Attempt provenance schema version | `backend/src/intric/flows/flow_run_provenance.py:22`, `backend/src/intric/flows/flow_run_provenance.py:85` | Current writer emits v1, but parser still accepts unversioned raw dicts through reconstruction. | `flow_run_provenance.py` | Harden parser around explicit v1. |
| Persisted attempt provenance export shape | `backend/src/intric/flows/flow_run_evidence_bundle.py:153` | Redacted bundle normalizes attempts, raw bundle does not; corrupt/missing versions can leak or crash inconsistently. | `flow_run_evidence_bundle.py` | Route raw and redacted attempt export through the same provenance parser result. |
| Manifest persisted provenance status | `backend/src/intric/flows/flow_run_export_json.py:150` | Manifest always says `not_tracked`, even after 7A.2 started writing schema versions. | `flow_run_export_json.py` | Compute `not_tracked` / `tracked` / `corrupt` from exported attempt provenance markers. |
| Runtime provenance writer | `backend/src/intric/flows/runtime/executor.py:183` | Writer builds v1 then mutates the dict after `to_payload()`, making future top-level additions easy to forget in the parser model. | `FlowAttemptProvenance` model validation | Build the full payload first, validate through `FlowAttemptProvenance`, then dump. Add a writer round-trip regression test. |
| Historical provenance reader | none | No row-count proof of historical shipped data. | none in this slice | Do not create a compatibility reader for unversioned branch-local data. Unversioned provenance is a corruption marker unless row proof changes this decision. |

### Historical Reader Decision

No historical reader ships in 7A.3.

Evidence:

- Flow/Flow AI Builder are pre-production on this branch.
- `docker exec eneo-41ae93-eneo-1 ...` is blocked by the local Codex tool approval policy before Docker execution, so no persisted row-count proof is available from the devcontainer in this environment.
- Current runtime writes provenance through `FlowAttemptProvenance(...).to_payload()` and therefore emits `schema_version`.
- Existing tests that seed unversioned provenance are test fixtures, not proof of shipped persisted data; they should be updated to v1 unless they intentionally test the corruption marker.

Re-entry trigger:

- Add a named historical reader only if a later human-approved data inspection proves real persisted rows with a known older schema/version. That reader must document schema/version, owner, deletion condition, and tests.

### Planned Shape

1. Add explicit parser result types in `flow_run_provenance.py`:
   - current/tracked result with `FlowAttemptProvenance`
   - not-tracked result when persisted value is `None`
   - corruption result with a typed marker payload
2. Add a strict typed corruption marker payload:
   - Pydantic `BaseModel` with `ConfigDict(extra="forbid")`
   - marker schema version `flow-attempt-provenance-marker.v1`, intentionally distinct from `flow-attempt-provenance.v1`
   - status `corrupt`
   - stable error code
   - short message
   - raw value type where safe
3. Treat these as corruption:
   - non-dict provenance values
   - missing `schema_version`
   - unsupported `schema_version`
   - unknown top-level keys for current v1 provenance
   - Pydantic validation failure while normalizing current v1 provenance
4. Keep nested provenance sections additive only where their existing nested models already allow `extra="allow"`; top-level provenance remains strict.
5. Preserve `normalize_attempt_provenance(raw)` as the canonical persisted-row normalizer for callers that only need the current v1 model. It returns a provenance object only for valid current v1 payloads.
6. Update `EvidenceBundle.to_dict()` and redaction path so both raw and redacted exports use the same parsed/marked attempt provenance. Chosen mechanism: add an `EvidenceBundlePayload` value object carrying both the serialized `payload` and the typed `provenance_parse_results`; `EvidenceBundle.to_export_payload()` and `RedactedEvidenceBundle.to_export_payload()` return that value object, while `to_dict()` remains a payload-only convenience wrapper.
7. Make `render_evidence_json_export` consume the bundle's typed provenance parse results instead of re-scanning serialized marker bytes for manifest status.
8. Update runtime `_build_attempt_provenance` so it builds the full payload, validates it through `FlowAttemptProvenance`, and only then persists/dumps it. Do not mutate after `to_payload()`.
9. Update manifest construction so:
   - no attempts with provenance yields `provenance_persisted_version_status="not_tracked"`
   - any corruption marker yields `"corrupt"`
   - at least one valid v1 provenance and no corrupt markers yields `"tracked"`
   - a mix of valid v1 provenance and `None` also yields `"tracked"` because per-attempt `provenance_json` still carries the precise absence/corruption state; no public `partial` enum is needed for Batch 8/9 lineage.
10. Do not add structured logs/metrics/audit rows yet. The export marker is the 7A.3 corruption surface. Batch 10 owns operational metrics/runbooks.
11. The corruption marker replaces `step_attempts[i].provenance_json` only in the export bundle. The typed `FlowRunEvidenceResponse` read-model contract remains unchanged in 7A.3; frontend evidence handling stays deferred to 7A.7.

### Behavior Pins Before And With Changes

- Current valid v1 provenance parses normally and retains `schema_version`.
- Missing schema version produces an explicit corruption marker and does not crash raw or redacted evidence export.
- Unsupported schema version produces an explicit corruption marker.
- Unknown top-level keys produce an explicit corruption marker instead of being silently dropped.
- Invalid non-dict provenance produces an explicit corruption marker.
- Manifest status is `tracked` for valid current provenance.
- Manifest status is `corrupt` when any exported attempt has a corruption marker.
- Manifest status remains `not_tracked` when attempts have no provenance.
- Raw and redacted exports share the same corruption marker behavior.
- Runtime writer output round-trips through the strict v1 model.
- HTTP evidence export shows `provenance_persisted_version_status="corrupt"` for a run with a corrupt persisted attempt.

### Expected Source/Test Changes For 7A.3

Expected source:

- `backend/src/intric/flows/flow_run_provenance.py`
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
- `backend/src/intric/flows/flow_run_export_json.py`
- `backend/src/intric/flows/runtime/executor.py`

Expected tests:

- `backend/tests/unittests/flows/test_flow_run_evidence.py`
- `backend/tests/unittests/flows/test_step_attempt_runtime.py`
- `backend/tests/unittests/flows/test_flow_run_service.py` only if service-level export status coverage needs a focused pin
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` for the public corrupt-manifest status pin
- `backend/tests/unit/test_flow_openapi_contract.py` only if marker schema is exposed as an API component

Expected docs:

- `docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-4.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-4.md`

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- migrations
- frontend evidence UI
- package names or `intric.*` namespace paths

### Acceptance Criteria For 7A.3

- Current `FlowAttemptProvenance` emits and parses explicit `flow-attempt-provenance.v1`.
- Corrupt, missing-version, and unsupported-version provenance produce visible markers instead of silent coercion or export crashes.
- Export manifest declares both export schema version and current/min provenance schema version.
- Export manifest reports persisted provenance version status as `not_tracked`, `tracked`, or `corrupt` based on the exported attempts.
- No historical reader is added without persisted row-count proof.
- Raw/redacted evidence exports preserve the same provenance parser behavior.
- No raw payload retention, migration, evidence ledger, frontend UI rewrite, package rename, or namespace migration is introduced.

### Validation Commands For 7A.3

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_step_attempt_runtime.py \
  tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail \
  -q
```

```bash
cd backend && uv run pytest \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment \
  tests/unit/test_flow_openapi_contract.py \
  tests/unit/test_server_startup_imports.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/runtime/executor.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_step_attempt_runtime.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/runtime/executor.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_step_attempt_runtime.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/runtime/executor.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_step_attempt_runtime.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
rg -n "legacy provenance|historical reader|flow-attempt-provenance\\.v0|Batch 7A|7A\\.|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)" \
  backend/src/intric/flows/flow_run_provenance.py \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/runtime/executor.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/unittests/flows/test_step_attempt_runtime.py
```

```bash
git diff --check -- \
  backend/src/intric/flows/flow_run_provenance.py \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/runtime/executor.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/unittests/flows/test_step_attempt_runtime.py \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-4.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-4.md
```

Docker/devcontainer validation:

```bash
docker exec eneo-41ae93-eneo-1 true
```

If the local tool policy rejects Docker before execution, record the exact rejection in the journal and use local/testcontainers validation.

### Claude Plan Review Question For 7A.3

Ask Claude:

```text
Attack this 7A.3 provenance version/corruption plan. Does it make attempt provenance schema-version-aware without adding fake historical compatibility, a parallel evidence ledger, or raw payload retention? Are the canonical owners right: flow_run_provenance.py for parser/marker, flow_run_evidence_bundle.py for persisted row normalization, and flow_run_export_json.py for manifest summary? Are the validation commands and behavior pins sufficient before Batch 8/9 lineage work?
```

Do not implement 7A.3 until Claude plan review returns green or Codex documents a source-backed disagreement.

## Completed Slice 7A.2

## Scope For 7A.2

### Goals

- Replace the loose export manifest `dict[str, Any]` with a typed export manifest model.
- Keep `flow_run_export_json.py` as the canonical JSON export renderer and manifest-construction owner.
- Preserve one normalized export path for raw and redacted bundles: serialize exactly the bundle that is returned, hash that normalized payload, and declare whether the hash input was `raw` or `redacted`.
- Add explicit manifest fields for export schema version, provenance compatibility, content hash input, export timestamp, tenant/run/trace/flow identity, exported user id, export reason, detail mode, redaction policy version, retention state summary, artifact availability summary, and current provenance version marker.
- Treat the manifest as the authoritative home for `schema_version` and `content_hash`; keep top-level `schema_version` and `content_hash` only as response-envelope mirrors with equality tests.
- Update the API response model so OpenAPI/generated-client-sensitive schema stops exposing the manifest as an untyped bag. The export `bundle` remains an unmodified evidence object because response-model coercion must not alter the bytes covered by `content_hash`.
- Keep the checked-in generated schema aligned with the OpenAPI contract touched in this slice.

### Non-Goals

- No new evidence ledger, migration, or table.
- No raw prompt/completion retention.
- No retention tombstone implementation; 7A.5 owns tombstone storage and deletion semantics.
- No artifact/file ownership migration; 7A.6 owns `FlowRunStepResultFiles` + `Files` canonical export.
- No strict provenance parser or corruption marker; 7A.3 owns parser behavior. 7A.2 may add only the explicit current provenance schema version constant required before an export-schema bump.
- No `audit_event_id` field in this slice. The audit service does not currently return a durable audit row id, and shipping a permanent-null public field would create speculative API debt.
- No frontend evidence UI/view-model rewrite; 7A.7 owns frontend evidence alignment if backend schema changes require it.
- No Batch 8 rerun behavior, Batch 9 human review behavior, package rename, or `intric.*` namespace migration.

### Canonical Owner Decisions

| Concept | Current locations | Problem | Canonical home for 7A.2 | Decision |
|---|---|---|---|---|
| Export JSON rendering and hash calculation | `backend/src/intric/flows/flow_run_export_json.py:60`, `backend/src/intric/flows/flow_run_export_json.py:73` | Renderer computes a hash but does not declare whether raw or redacted payload was hashed. | `flow_run_export_json.py` | Keep and harden. Add typed export context and manifest construction here. |
| Export manifest shape | `backend/src/intric/flows/flow_run_export_json.py:114`, `backend/src/intric/flows/api/flow_models.py:1313` | Runtime and OpenAPI expose a loose `dict[str, Any]`, making generated clients weak. | `flow_run_evidence_export_manifest.py` | Create one narrow leaf module for typed manifest/context models. It imports only typing/Pydantic/provenance constants and must be added to `.importlinter`'s Flow engine source list. |
| Export bundle integrity | `backend/src/intric/flows/api/flow_run_evidence_router.py:277`, `backend/src/intric/flows/api/flow_models.py:1339` | Validating the attachment bundle through the read-model schema can drop export-only evidence fields and invalidate the content hash. | `FlowRunEvidenceExportResponse.bundle` | Keep the manifest typed and declare the export bundle as open JSON so the served attachment preserves the exact object that was hashed. |
| Export reason | Router audit metadata in `backend/src/intric/flows/api/flow_run_evidence_router.py:265` | Reason is audit-visible but absent from the export manifest. | `FlowRunService.export_evidence_json` parameter passed to renderer | Add an optional/explicit export context. Router passes the already-validated reason. Service tests may use the redacted default when no reason is supplied. |
| Audit event id | `audit_service.log_async` calls in evidence router | Current audit service call does not return a persisted audit row id. | Deferred to audit durability slice | Do not add an `audit_event_id` field until a real producer exists. |
| Provenance schema compatibility | `backend/src/intric/flows/flow_run_provenance.py:82` | Attempt provenance has no explicit schema version today. | `flow_run_provenance.py` constant and `FlowAttemptProvenance` payload field if safe | Add the explicit current/min schema version only if required for export v3 and testable without strict parser work. Strict parser/corruption remains 7A.3. |
| Retention/artifact summaries | Export summary derives from bundle payload JSON | Current export cannot prove tombstones or canonical file availability yet. | Typed manifest summary fields with truth-telling current states | Use explicit `not_tracked`/zero-count states where canonical data is not available. Do not imply content availability that is not tracked. |

### Planned Shape

Revised implementation after Claude plan review:

1. Add a narrow typed manifest module with no persistence, HTTP, or framework ownership:
   - `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
2. Define:
   - `EVIDENCE_EXPORT_SCHEMA_VERSION: Literal["flow-evidence-export.v3"]`
   - `EvidenceExportContentHashInput = Literal["raw", "redacted"]`
   - `EvidenceExportDetailMode = Literal["raw", "redacted"]`
   - `EvidenceExportContext`
   - `EvidenceRetentionStateSummary`
   - `EvidenceArtifactAvailabilitySummary`
   - `EvidenceExportManifest`
   - Summary models use `ConfigDict(extra="allow")` only for future additive fields from 7A.5/7A.6; the required fields listed below remain explicit and tested.
   - `EvidenceExportManifest` and `EvidenceExportContext` use `ConfigDict(extra="forbid")`; tests must prove unknown manifest fields fail validation.
3. Add a `FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION` constant in `flow_run_provenance.py`; use it in the manifest as the current/min provenance schema version. Do not implement strict historical parsing or corruption markers in this slice.
4. Keep `render_evidence_json_export` returning the public export dict, but build the manifest through `EvidenceExportManifest.model_validate(...).model_dump(mode="json")`.
5. Pass a single `EvidenceExportContext` from `FlowRunService.export_evidence_json` to the renderer. Do not widen the renderer with loose kwargs.
6. Manifest is canonical for `schema_version` and `content_hash`. The top-level `schema_version` and `content_hash` mirror `manifest.schema_version` and `manifest.content_hash` and are tested for equality.
7. Update `FlowRunEvidenceExportResponse.manifest` from `dict[str, Any]` to the typed manifest model. Keep `FlowRunEvidenceExportResponse.bundle` as open JSON to preserve the exact hashed export payload through HTTP response validation.
8. Update `.importlinter` to include the new manifest module in the Flow engine no-AI-Builder source list.
9. Update the OpenAPI contract tests and checked-in generated schema for manifest fields.

No fallback location is planned. `rg "from intric\\.flows\\.flow_run_export_json|from intric\\.flows\\.api\\.flow_models" backend/src` shows `flow_run_export_json.py` is imported by the application service and the API layer imports `flow_models.py`; a leaf manifest module avoids both a renderer-to-API inversion and a heavy API import of the full renderer.

### Manifest Field Shape

`EvidenceExportManifest` fields:

| Field | Type | Source | Notes |
|---|---|---|---|
| `schema_version` | `Literal["flow-evidence-export.v3"]` | Manifest module constant | Authoritative. Top-level `schema_version` mirrors this value. |
| `provenance_schema_version_min` | `str` | `FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION` | Lowest persisted provenance schema version the export builder currently accepts as compatible. It equals current until 7A.3 introduces historical parsing. |
| `provenance_schema_version_current` | `str` | `FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION` | Export builder current version, not a per-row parser verdict. |
| `provenance_persisted_version_status` | `Literal["not_tracked", "tracked", "corrupt"]` | Current limitation | 7A.2 emits only `not_tracked`; 7A.3 may emit `tracked` or `corrupt` without an export-schema bump. |
| `content_hash` | `str` | Normalized returned `bundle` payload | Authoritative. Top-level `content_hash` mirrors this value. |
| `content_hash_input` | `Literal["raw", "redacted"]` | Export detail | Declares whether the raw or redacted returned bundle was hashed. |
| `exported_at` | `datetime` | Renderer clock | Top-level `generated_at` mirrors this timestamp for compatibility. |
| `tenant_id` | `str` | `bundle.run.tenant_id` | Required. |
| `run_id` | `str` | `bundle.run.id` | Required. |
| `trace_id` | `str` | `bundle.run.trace_id` | Required. |
| `flow_id` | `str` | `bundle.run.flow_id` | Required. |
| `flow_version` | `int` | `bundle.run.flow_version` | Required; Flow run persistence and domain models make this non-null. |
| `exported_by_user_id` | `str | None` | `FlowRunService.user.id` | Explicitly user id only. Principal/service-key identity remains in audit metadata until a principal model is exposed to the service. |
| `export_reason` | `str` | Router/service export context | Raw is explicit; redacted may use `support_debug` until a later UX/API decision. |
| `detail_mode` | `Literal["raw", "redacted"]` | Export context | Mirrors hash input semantics. |
| `redaction_applied` | `bool` | Redacted bundle/security state | Kept from the 7A.1 manifest pin. Mirrors `redaction.applied`; equality is tested. |
| `masked_fields_count` | `int` | Redacted bundle/security state | Kept from the 7A.1 manifest pin. Mirrors `redaction.masked_fields_count`; equality is tested. |
| `redaction_policy_version` | `str` | `REDACTION_POLICY_VERSION` | Redactor build-policy version. Always emitted; does not imply redaction was applied. |
| `retention_state_summary` | `EvidenceRetentionStateSummary` | Current export limitation | Truthfully says retention tombstones are not tracked yet. |
| `artifact_availability_summary` | `EvidenceArtifactAvailabilitySummary` | Current bundle payload scan | Truthfully says canonical artifact/file availability is not fully tracked yet. |

This table is exhaustive for the 7A.2 manifest. `redaction_applied` and `masked_fields_count` intentionally remain in the manifest because 7A.1 pinned them as the migration target. The top-level `redaction` block remains the detailed redaction owner; manifest redaction fields are summary mirrors and must be tested for equality with the top-level block.

`EvidenceRetentionStateSummary` fields:

| Field | Type | Current value |
|---|---|---|
| `tracking_state` | `Literal["not_tracked", "tracked"]` | `not_tracked`; 7A.5 may emit `tracked` without a schema bump. |
| `tombstone_count` | `int` | `0` |
| `retention_purged_count` | `int` | `0` |
| `redacted_for_deletion_count` | `int` | `0` |
| `note` | `str` | Explains that 7A.5 owns tombstone tracking. |

`EvidenceArtifactAvailabilitySummary` fields:

| Field | Type | Current value |
|---|---|---|
| `tracking_state` | `Literal["payload_derived"]` | `payload_derived` |
| `payload_artifact_count` | `int` | Count from current export summary artifact details. |
| `note` | `str` | Explains that canonical file availability is not yet exposed and will be expanded when file-row availability becomes trackable. Runtime text must not reference 7A or internal plan labels. |

7A.2 deliberately keeps artifact availability summary small. 7A.6 owns real canonical file-row availability counts and may extend this model under the v3 schema because the current shape declares only what is truthfully known today.

### Source Verification For Required Manifest Identity Fields

- `FlowRun.flow_version` is non-null in the domain model and database table: `backend/src/intric/flows/domain/flow.py:132`, `backend/src/intric/database/tables/flow_tables.py:334`.
- `FlowRun.trace_id` is non-null in the domain model and database table: `backend/src/intric/flows/domain/flow.py:138`, `backend/src/intric/database/tables/flow_tables.py:357`.
- `rg -n "trace_id\\s*[:=].*None|flow_version\\s*[:=].*None|trace_id:.*None|flow_version:.*None" backend/src/intric/flows backend/tests` found optional request/response fields and tests for expected-flow-version inputs, but no FlowRun persistence fixture that sets `trace_id` or `flow_version` to `None`.

### Behavior Pins Before Implementation

- Current redacted export hash pin from `backend/tests/unittests/flows/test_flow_run_service.py:2979` must be rewritten to assert:
  - `content_hash` equals the normalized returned redacted bundle hash.
  - `manifest.content_hash_input == "redacted"`.
  - `manifest.content_hash == content_hash`.
  - The exact re-serialization assertion over `json.dumps(export["bundle"], sort_keys=True, separators=(",", ":"))` remains, proving the hash is not over the whole envelope or a manifest-included variant.
- Add a raw export counterpart proving:
  - raw export hashes the raw returned bundle.
  - `manifest.content_hash_input == "raw"`.
  - raw/redacted exports share the same top-level shape and manifest field set.
- Add an explicit set-equality test: `set(raw_export.keys()) == set(redacted_export.keys())` and `set(raw_export["manifest"]) == set(redacted_export["manifest"])`.
- Add equality tests for manifest summary mirrors:
  - `export["manifest"]["schema_version"] == export["schema_version"]`
  - `export["manifest"]["content_hash"] == export["content_hash"]`
  - `export["manifest"]["exported_at"] == export["generated_at"]`
  - `export["manifest"]["redaction_applied"] == export["redaction"]["applied"]`
  - `export["manifest"]["masked_fields_count"] == export["redaction"]["masked_fields_count"]`
- Add a manifest validation test proving an unknown field raises instead of being accepted silently.
- Strengthen `backend/tests/unittests/flows/test_flow_run_evidence.py:355` to assert the typed manifest field set and truth-telling defaults for retention state and artifact availability.
- Strengthen `backend/tests/integration/flows/test_flow_evidence_api_contracts.py:489` to assert representative manifest v3 fields on the HTTP attachment path and re-hash the actual served `payload["bundle"]`.
- Strengthen OpenAPI/generated-client contract tests so `manifest` is no longer an untyped free-form object.

### Planned Source/Test Changes For 7A.2

Expected source changes:

- `backend/src/intric/flows/flow_run_export_json.py`
- `backend/src/intric/flows/application/flow_run_service.py`
- `backend/src/intric/flows/api/flow_run_evidence_router.py`
- `backend/src/intric/flows/api/flow_models.py`
- `backend/src/intric/flows/flow_run_provenance.py` only if the explicit provenance schema version constant/field is needed before export v3.
- `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
- `backend/.importlinter`
- `frontend/packages/intric-js/src/types/schema.d.ts` for the generated-client-sensitive schema surface touched by this slice.
- `frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts` for package-local type smoke coverage of the generated evidence export alias.

Expected test changes:

- `backend/tests/unittests/flows/test_flow_run_evidence.py`
- `backend/tests/unittests/flows/test_flow_run_service.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
- `backend/tests/unit/test_flow_openapi_contract.py`
- `backend/tests/unit/test_server_startup_imports.py` only if the OpenAPI example path changes.
- `backend/tests/unittests/flows/test_flow_router.py` only if router export reason/context assertions need updating.

Expected docs changes:

- `docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-{N}.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-{N}.md`

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- frontend evidence UI files in 7A.2
- migrations
- Batch 8 or Batch 9 files

### Acceptance Criteria For 7A.2

- Raw and redacted evidence exports use the same top-level export shape and a single manifest builder.
- Manifest is typed in runtime construction and OpenAPI response schema.
- Manifest includes explicit `content_hash_input` with correct raw/redacted semantics.
- Manifest includes `exported_at`, tenant/run/trace/flow identity, detail mode, export reason, exported user id where available, redaction policy version, retention summary, artifact availability summary, and provenance compatibility fields.
- Export hash tests prove the hash is over the exact returned `bundle` payload, including the actual HTTP attachment payload after response validation.
- OpenAPI/generated-client-sensitive schema shows a typed manifest instead of `dict[str, Any]`.
- The journal records the `flow-evidence-export.v2` to `flow-evidence-export.v3` bump, the field-level manifest changes, and the pre-production/no-external-SDK-release rationale.
- No raw payload retention, migration, evidence ledger, frontend UI rewrite, package rename, or namespace migration is introduced.

### Validation Commands For 7A.2

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_hashes_returned_bundle_and_manifest_by_detail \
  -q
```

```bash
cd backend && uv run pytest \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment \
  tests/unit/test_flow_openapi_contract.py \
  tests/unit/test_server_startup_imports.py \
  -q
```

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_returns_json_attachment \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_passes_raw_detail_and_reason \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_rejects_raw_invalid_reason \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/flow_run_evidence_export_manifest.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_models.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/flow_run_evidence_export_manifest.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_models.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/flow_run_evidence_export_manifest.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/application/flow_run_service.py \
  src/intric/flows/api/flow_run_evidence_router.py \
  src/intric/flows/api/flow_models.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_flow_run_service.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
cd frontend/packages/intric-js && bun run check
```

```bash
cd frontend/packages/intric-js && bun run lint
```

```bash
rg -n "manifest: dict\\[str, Any\\]|flow-evidence-export\\.v2|Batch 7A|7A\\.|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)" \
  backend/.importlinter \
  backend/src/intric/flows/flow_run_evidence_export_manifest.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/flow_run_provenance.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/src/intric/flows/application/flow_run_service.py \
  backend/src/intric/flows/api/flow_run_evidence_router.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/unittests/flows/test_flow_run_service.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  frontend/packages/intric-js/src/types/schema.d.ts \
  frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts
```

Expected: no committed source/test planning vocabulary. `flow-evidence-export.v2` should remain only in tests/docs if verifying migration away from v2, not as the new runtime schema version.

```bash
git diff --check -- \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/flow_run_evidence_export_manifest.py \
  backend/src/intric/flows/flow_run_provenance.py \
  backend/src/intric/flows/application/flow_run_service.py \
  backend/src/intric/flows/api/flow_run_evidence_router.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/unittests/flows/test_flow_run_service.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  frontend/packages/intric-js/src/types/schema.d.ts \
  frontend/packages/intric-js/src/types/flow-resource-aliases.types.ts \
  backend/.importlinter \
  docs/refactor/execution/batch-7a-evidence-provenance-contract
```

### Claude Plan Review Question For 7A.2

Ask Claude:

```text
Attack this 7A.2 typed manifest plan. Does it put the export manifest in the right canonical owner, avoid a parallel evidence system, preserve raw/redacted hash semantics, and satisfy the hard gates without starting provenance parser, retention tombstone, artifact ownership, frontend, rerun, or review work too early? Should the typed manifest model live in a new narrow export-contract module, in flow_run_export_json.py, or in API flow_models.py?
```

Do not implement 7A.2 until Claude plan review returns green or Codex documents a source-backed disagreement.

## Scope For 7A.1

### Goals

- Establish the canonical owners for Flow evidence/provenance before rerun and human review add lineage.
- Pin current evidence API/export behavior before deleting unreachable branches or changing export validation.
- Delete never-shipped evidence compatibility where the public API already rejects it, including generated-client-sensitive documentation of that deleted surface.
- Record carry-forward gaps for typed manifests, provenance schema versioning, tool-call single source of truth, RAG truthfulness states, retention tombstones, artifact/file ownership, frontend view-model alignment, and export size thresholds.

### Non-Goals

- No step rerun behavior.
- No human review pause/edit/resume behavior.
- No migrations or new evidence ledger table.
- No raw prompt/completion storage.
- No frontend evidence UI changes in 7A.1.
- No generated-client/package rename.
- No `intric.*` to `eneo.*` namespace migration.

## Input Notes

- The prompt references `docs/refactor/prd/PRD-007-dead-code-and-compatibility-cleanup.md` and `docs/refactor/prd/PRD-008-test-suite-quality-and-speed.md`, but the repository contains:
  - `docs/refactor/prd/PRD-007-testing-strategy.md`
  - `docs/refactor/prd/PRD-008-dead-code-comments-and-readability.md`
- `docs/refactor/implementation-order.md` has no official row for inserted Batch 7A. Validation commands below are exact shell commands derived from the Batch 7A prompt expectations and adjacent official Batch 8/9 evidence requirements.
- Docker validation is blocked in this Codex environment by host policy: `docker ps --format '{{.Names}}'` was rejected because approval is required while approval policy is `Never`. Use local fallback validation unless a later run can execute Docker without elevated approval.
- Claude plan review iteration 1 returned `GREEN_LIGHT: no`; accepted findings are folded into this revision.

## Product Claim Boundary

Evidence export must prove what Eneo sent, received, stored, derived, redacted, retained, or deleted. It must not claim to explain the model's internal reasoning.

## Canonical Evidence Owner Inventory

| Concept | Current owner | Evidence | 7A.1 decision | Later slice |
|---|---|---|---|---|
| Evidence HTTP adapter and audit fail-closed boundary | `flow_run_evidence_router.py` | `backend/src/intric/flows/api/flow_run_evidence_router.py:65`, `backend/src/intric/flows/api/flow_run_evidence_router.py:137`, `backend/src/intric/flows/api/flow_run_evidence_router.py:247` | Keep. Tighten raw export reason behavior and remove unreachable custom format fallback if pins pass. | 7A.2/7A.8 may refine OpenAPI/download contract. |
| Evidence bundle read model | `flow_run_evidence_bundle.py` | `backend/src/intric/flows/flow_run_evidence_bundle.py:62`, `backend/src/intric/flows/flow_run_evidence_bundle.py:83` | Keep. No new ledger. | 7A.2 typed manifest and normalized raw/redacted path. |
| JSON export summary and manifest | `flow_run_export_json.py` | `backend/src/intric/flows/flow_run_export_json.py:60`, `backend/src/intric/flows/flow_run_export_json.py:114` | Keep as current export renderer; pin its current loose manifest limitations. | 7A.2 typed manifest and explicit hash input. |
| Attempt provenance | `FlowStepAttempts.provenance_json` plus `flow_run_provenance.py` | `backend/src/intric/database/tables/flow_tables.py:568`, `backend/src/intric/flows/flow_run_provenance.py:82`, `backend/src/intric/flows/runtime/executor.py:177` | Keep. Do not add parser/versioning yet in 7A.1. | 7A.3 schema version, strict parser, corruption marker. |
| Tool-call evidence | Currently duplicated between attempt provenance and result row metadata | `backend/src/intric/flows/runtime/executor.py:187`, `backend/src/intric/flows/runtime/step_execution_runtime.py:988`, `backend/src/intric/flows/infrastructure/flow_repo.py:542`, `backend/src/intric/database/tables/flow_tables.py:499` | Inventory only. Do not delete in 7A.1 because API schema and retention cleanup still read/write it. | 7A.4 single-source normalization. |
| Result artifact/file evidence | `FlowRunStepResultFiles` + `Files`, with legacy JSON scanning still in export/readers | `backend/src/intric/database/tables/flow_tables.py:680`, `backend/src/intric/database/tables/files_table.py:14`, `backend/src/intric/flows/infrastructure/flow_repo.py:578`, `backend/src/intric/flows/flow_run_export_json.py:453` | Keep canonical rows. Do not delete JSON scanning in 7A.1 because artifact API still reads payload JSON. | 7A.6 artifact/file evidence ownership. |
| Retention cleanup | `DataRetentionService` | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:48`, `backend/src/intric/data_retention/infrastructure/data_retention_service.py:387`, `backend/src/intric/data_retention/infrastructure/data_retention_service.py:458` | Inventory gap. No tombstone migration in 7A.1. | 7A.5 tombstones and deletion semantics. |
| Frontend evidence grouping/parsing | `flowEvidenceProvenance.ts` plus Svelte components | `frontend/apps/web/src/lib/features/flows/flowEvidenceProvenance.ts:20`, `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:40` | No frontend changes in 7A.1. | 7A.7 if backend schema changes. |

## Dead Code / Legacy Compatibility Inventory

| concept | current locations | shipped/persisted data need? | keep/delete/rewrite | canonical owner | deletion condition |
|---|---|---|---|---|---|
| Custom unsupported evidence export format branch | `backend/src/intric/flows/api/flow_run_evidence_router.py:198`, `backend/src/intric/flows/api/flow_run_evidence_router.py:232`; direct-function test `backend/tests/unittests/flows/test_flow_router.py:2142`; OpenAPI startup assertion `backend/tests/unit/test_server_startup_imports.py:282`; generated schema docs `frontend/packages/intric-js/src/types/schema.d.ts:34051` | No. The FastAPI parameter is `Literal["json"]`; unsupported HTTP values are request validation, not runtime evidence behavior. | Delete branch and direct-function test; replace the stale 400 example with raw-reason validation; update generated-client-sensitive docs for the changed 400 shape. | Evidence router/OpenAPI contract. | OpenAPI test proves only JSON is exposed; repo-wide `rg` finds no remaining unsupported-format error code outside historical docs. |
| Raw export reason defaulting to support reason | `backend/src/intric/flows/api/flow_run_evidence_router.py:205`; frontend redacted caller omits reason at `frontend/apps/web/src/lib/features/flows/components/flowRunEvidenceActions.ts:57`; package wrapper omits reason at `frontend/packages/intric-js/src/endpoints/flows.js:612` | Redacted support export callers exist and currently rely on default support reason. Raw callers without reason were not found outside tests/service calls. | Keep redacted default `support_debug`; reject raw export when the reason is omitted, blank, or the generic default. Add tests proving redacted default still audits and raw default does not export/audit. | Evidence router audit boundary. | Router/unit tests and OpenAPI docs prove raw requires an explicit reason while redacted remains backward-compatible inside this pre-production branch. |
| Debug export v1 fixtures in router unit tests | `backend/tests/unittests/flows/test_flow_router.py:1930`, `backend/tests/unittests/flows/test_flow_router.py:2375` | Fixture drift only; no historical reader. | Normalize both fixtures to current v2 in this slice because the file is touched for evidence-router tests. | Test fixture owner. | No `eneo.flow.debug-export.v1` remains in `test_flow_router.py`. |
| Result JSON artifact scanning | `backend/src/intric/flows/flow_run_export_json.py:453`, `backend/src/intric/flows/application/flow_run_service.py:770`, retention scanning `backend/src/intric/data_retention/infrastructure/data_retention_service.py:707` | Temporary public/API behavior until `FlowRunStepResultFiles` owns export/download. | Keep in 7A.1; record as carry-forward. | `FlowRunStepResultFiles` + `Files`. | 7A.6 migrates readers and tests prove canonical row ownership. |
| `tool_calls_metadata` result column | `backend/src/intric/database/tables/flow_tables.py:499`, API schema `backend/src/intric/flows/api/flow_models.py:535`, persistence `backend/src/intric/flows/infrastructure/flow_repo.py:542`, runtime writer `backend/src/intric/flows/runtime/step_execution_runtime.py:988`, retention cleanup `backend/src/intric/data_retention/infrastructure/data_retention_service.py:405` | Persisted rows may exist on this branch; API exposes it. | Keep in 7A.1; record duplicate owner risk and current reader/writer inventory. | Attempt provenance unless a named API/UI reader requires derived summary. | 7A.4 migrates readers and deletes or formally derives the summary. |
| Frontend runtime file/template historical readers | `frontend/apps/web/src/lib/features/flows/flowEvidenceProvenance.ts:20`, `frontend/apps/web/src/lib/features/flows/flowEvidenceProvenance.ts:39` | Public evidence display currently depends on these shapes. | Keep in 7A.1. | Frontend evidence view model until generated evidence schema changes. | 7A.7 replaces with generated-backed view model if backend schema changes. |
| Retention destructive cleanup without tombstones | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:387`, `backend/src/intric/data_retention/infrastructure/data_retention_service.py:458` | Current behavior exists but is incomplete for audit-grade evidence. | Keep in 7A.1; record gap. | Retention service and future tombstone owner. | 7A.5 designs tombstone storage with migration decision. |

## Behavior Pins Before Destructive Work

7A.1 will add or strengthen pins in this order:

1. **OpenAPI/download contract pin**: export endpoint documents JSON attachment and `format` is JSON-only.
   - Existing: `backend/tests/unit/test_flow_openapi_contract.py:676`, `backend/tests/unit/test_flow_openapi_contract.py:862`.
   - Add/strengthen: assert the `format` schema enum/default exposes only `json`; assert raw reason documentation mentions raw export requires an explicit reason; update startup import contract away from the deleted unsupported-format 400 code.
2. **Raw export reason validation pin**: raw export without a concrete reason returns a stable error and does not call export or audit.
   - Existing raw positive pin: `backend/tests/unittests/flows/test_flow_router.py:2315`.
   - Add: negative direct router pin. Raw `reason="support_debug"` is rejected as non-specific; redacted default remains allowed because current frontend/package callers depend on it.
3. **Audit fail-closed export pin**: export does not return evidence if audit persistence fails.
   - Existing unit pin: `backend/tests/unittests/flows/test_flow_router.py:2263`.
   - Add: integration-level pin by mirroring `backend/tests/integration/flows/test_flow_evidence_api_contracts.py:593`.
4. **Unreachable unsupported-format cleanup pin**: after the OpenAPI pin proves only JSON is public, delete the direct-function unsupported-format test and branch.
5. **Manifest key-set pin**: before the typed manifest migration, assert the current manifest keys and basic value types so 7A.2 has a stable migration target: `run_id`, `flow_id`, `trace_id`, `flow_version`, `content_hash`, `redaction_applied`, `masked_fields_count`, and `redaction_policy_version`.
6. **Retention/deletion marker gap**: record the missing tombstone/export availability marker behavior as carry-forward for 7A.5. Do not add failing tests in 7A.1 because a tombstone store is a schema decision.

## Caller Inventory For Deferred Duplicate Owners

### Tool-call evidence duplication

Current writer/reader list:

- Runtime captures completion tool calls in `backend/src/intric/flows/runtime/step_execution_runtime.py:988`.
- Attempt provenance also stores a preview of tool calls from `backend/src/intric/flows/runtime/executor.py:187`.
- Result persistence writes denormalized `tool_calls_metadata` in `backend/src/intric/flows/infrastructure/flow_repo.py:542`.
- API schema exposes result-row `tool_calls_metadata` in `backend/src/intric/flows/api/flow_models.py:535`.
- Retention cleanup clears result-row metadata in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:405`.
- Tests consume this field in `backend/tests/integration/flows/test_flow_evidence_api_contracts.py:279`, `backend/tests/unittests/flows/test_flow_models.py:186`, and several runtime fixtures.

7A.4 deletion condition: move all public evidence/export/UI readers to attempt provenance or define a named derived summary owner, migrate retention cleanup to that owner, and then delete the result-row field/tests only with a migration decision.

### Result artifact JSON scanning

Current reader list:

- Export summary scans `artifacts` and `generated_file_ids` in `backend/src/intric/flows/flow_run_export_json.py:453`.
- Artifact file lookup scans result payload JSON in `backend/src/intric/flows/application/flow_run_service.py:770`.
- Retention cleanup extracts generated files from JSON payloads in `backend/src/intric/data_retention/infrastructure/data_retention_service.py:707`.
- Persistence already writes canonical attempt-scoped result file rows in `backend/src/intric/flows/infrastructure/flow_repo.py:578`.

7A.6 deletion condition: export summary, artifact download, and retention cleanup all read `FlowRunStepResultFiles` + `Files` as the canonical owner, then JSON scanning becomes either deleted or a clearly named historical reader backed by row-count proof.

## Planned Source/Test Changes For 7A.1

Expected source changes:

- `backend/src/intric/flows/api/flow_run_evidence_router.py`
  - Remove unreachable custom unsupported-format branch.
  - Require a specific reason for `detail=raw`; return a typed 400 error before export/audit if missing, blank, or the generic `support_debug` default.
  - Define one default reason constant so the default and raw-rejection sentinel cannot drift apart.
  - Keep router as HTTP/audit boundary owner.

Expected test changes:

- `backend/tests/unit/test_flow_openapi_contract.py`
  - Strengthen evidence export query parameter contract pins.
- `backend/tests/unit/test_server_startup_imports.py`
  - Replace the deleted unsupported-format 400 assertion with the raw-reason 400 assertion.
- `backend/tests/unittests/flows/test_flow_router.py`
  - Remove unsupported-format direct function test.
  - Add raw export missing-reason negative behavior pin.
  - Keep raw export positive reason pin.
  - Normalize touched evidence fixtures to debug export v2.
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
  - Pin the current manifest key set and basic value types before 7A.2 changes it.
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py`
  - Add export audit fail-closed integration pin.
- `frontend/packages/intric-js/src/types/schema.d.ts`
  - Update the 400 example in the generated schema so the checked-in generated-client-sensitive documentation matches the OpenAPI response. Do not regenerate or rename the package in this slice.

Expected docs changes:

- `docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-{N}.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-{N}.md`
- `.codex/artifacts/claude-peer-loop-*.md` remain local artifacts and should not be staged unless explicitly promoted.

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- frontend evidence files in 7A.1
- migrations in 7A.1
- Batch 8 rerun files
- Batch 9 review pause/resume files

## Acceptance Criteria For 7A.1

- Evidence/provenance owner inventory exists with canonical owner decisions.
- Clearly unreachable evidence export compatibility is deleted rather than preserved.
- Raw export requires a concrete purpose and does not silently use a generic support reason; redacted default behavior remains pinned for current frontend/package callers.
- Evidence export audit fail-closed behavior remains pinned.
- The current loose manifest key set is pinned before typed manifest work begins.
- The plan records that typed manifest, provenance schema version, tool-call single source, RAG truthfulness, retention tombstones, artifact/file ownership, frontend evidence view-model cleanup, and size/performance semantics are carry-forward work for later 7A slices.
- No new evidence ledger, compatibility shim, raw payload retention, migration, frontend rewrite, package rename, or namespace rename is introduced.

## Validation Commands

Run these after implementation:

```bash
cd backend && uv run pytest \
  tests/unit/test_flow_openapi_contract.py \
  tests/unit/test_server_startup_imports.py \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_returns_json_attachment \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_passes_raw_detail_and_reason \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_fails_closed_when_audit_write_fails \
  tests/unittests/flows/test_flow_router.py::test_flow_run_evidence_export_alias_rejects_raw_invalid_reason \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  -q
```

```bash
cd backend && uv run pytest tests/unittests/flows/test_flow_run_evidence.py tests/unittests/flows/test_flow_run_service.py::test_export_evidence_json_returns_hashed_redacted_bundle -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/api/flow_run_evidence_router.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unit/test_server_startup_imports.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/api/flow_run_evidence_router.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unit/test_server_startup_imports.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/api/flow_run_evidence_router.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unit/test_server_startup_imports.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
rg -n "flow_evidence_export_format_not_supported|Evidence export format is not supported|support_debug.*raw|raw.*support_debug|Batch 7A|7A\\.|phase|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)" \
  backend/src/intric/flows/api/flow_run_evidence_router.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  backend/tests/unit/test_server_startup_imports.py \
  backend/tests/unittests/flows/test_flow_router.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  frontend/packages/intric-js/src/types/schema.d.ts
```

Expected: no source/test matches for deleted format fallback, raw support default leakage, or internal planning vocabulary. The docs directory may mention Batch 7A.

```bash
git diff --check -- \
  backend/src/intric/flows/api/flow_run_evidence_router.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  backend/tests/unit/test_server_startup_imports.py \
  backend/tests/unittests/flows/test_flow_router.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  frontend/packages/intric-js/src/types/schema.d.ts \
  docs/refactor/execution/batch-7a-evidence-provenance-contract
```

```bash
cd frontend/packages/intric-js && bun run check
```

```bash
cd frontend/packages/intric-js && bun run lint
```

```bash
git diff --name-only -- frontend/packages/ui/src/icons/types.d.ts scripts/run_codex_review.sh PRODUCT.md
```

Expected: these remain only the pre-existing unrelated dirty files and are not staged or modified by this slice.

## Claude Plan Review Packet

Ask Claude to attack:

- Is 7A.1 too small, too broad, or missing a safer first behavior pin?
- Is deleting the custom unsupported-format branch correct given the FastAPI `Literal["json"]` public contract?
- Is raw export reason validation the right first API hardening, or should it wait for the typed manifest slice?
- Are any historical readers misclassified as dead code?
- Does the plan accidentally preserve a second evidence source of truth without a deletion path?

Accepted Claude iteration-1 findings incorporated before implementation:

- unsupported-format deletion must also handle OpenAPI startup tests and generated-client-sensitive schema docs
- redacted/default reason policy must be explicit
- export audit fail-closed integration pin should be committed
- current manifest key set should be pinned before typed manifest work
- tool-call and artifact JSON duplicate-reader inventories should be recorded now

Proceed only after the same Claude session returns green light or after a documented evidence-based disagreement.

## Carry-Forward 7A Slices

- 7A.2: typed export manifest and normalized raw/redacted export path.
- 7A.2: run or explicitly verify the generated `intric-js` schema regeneration path so the hand-updated evidence export 400 example is confirmed by generated output before any SDK release.
- 7A.3: provenance schema versioning, strict parser, corruption markers.
- 7A.4: tool-call single-source normalization and RAG truthfulness states.
- 7A.5: retention tombstones and deletion semantics. This likely requires an explicit migration/data-model decision.
- 7A.6: artifact/file evidence ownership via `FlowRunStepResultFiles` and `Files`.
- 7A.7: frontend evidence generated aliases/view model if backend evidence schemas change.
