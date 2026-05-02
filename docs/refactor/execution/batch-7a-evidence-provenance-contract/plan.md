# Batch 7A — Evidence / Provenance Contract Foundation

## Active Next Plan

The active implementation slice is **7A.6 — Artifact/file evidence ownership**.

Official Batch 8 step rerun does not start until this inserted evidence/provenance foundation reaches a stable checkpoint. 7A.1 is committed at `5563bb71`, 7A.2 is committed at `d3228d83`, 7A.3 is committed at `1cd68a2d`, 7A.4 is committed at `78506836`, and 7A.5 is committed at `1c5bc7c2`. 7A.6 makes `FlowRunStepResultFiles` plus `Files` the canonical artifact evidence owner for export, signed artifact access, and retention cleanup.

## Scope For 7A.6

### Goals

- `FlowRunStepResultFiles` joined to `Files` is the only reader for artifact evidence availability, file metadata, and signed artifact eligibility.
- Evidence bundles include `result_files` in the hashed bundle payload so the export proves which artifact files were associated with the run.
- The evidence export manifest reports typed row-backed artifact availability: artifact count, available count, content-purged count, total size, and per-artifact checksum/size/mimetype/file-type/availability.
- Artifact signed URL generation distinguishes a missing artifact row from a known artifact whose content has been purged:
  - missing row: `404` with `flow_run_artifact_not_found`
  - known row with purged content: `410` with `flow_run_artifact_content_unavailable`
- Retention cleanup and display-cache pruning use result-file rows for the file-id set. JSON artifact keys are no longer evidence owners.
- Frontend display payload keys (`output_payload_json.artifacts` and `output_payload_json.generated_file_ids`) remain only because current frontend components still read them at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:504` and `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidenceStepCard.svelte:172`. 7A.7 deletion condition: once those components read `result_files`, runtime output stops writing those keys and the display-cache pruning code is deleted.

### Non-Goals

- No Batch 8 step rerun lineage behavior.
- No frontend view-model rewrite in this slice; 7A.7 owns generated/frontend evidence alignment after the backend schema change lands.
- No broad artifact service or new interface. `FlowRunRepository` owns run-artifact row association; `FileRepository` continues to own file content retrieval.
- No compatibility path for JSON-only Flow artifact evidence. Flow/Flow AI Builder is unreleased, so rows are required.
- No package rename or `intric.*` namespace migration.

### Canonical Ownership Map

| Concept | Current location | Problem | Canonical owner for 7A.6 | Delete/merge path |
|---|---|---|---|---|
| Artifact row association | `backend/src/intric/flows/infrastructure/flow_repo.py:578-648` writes `FlowRunStepResultFiles`; readers still scan JSON. | Write owner exists but readers use a parallel source. | `FlowRunStepResultFiles` via `FlowRunRepository` typed projection. | Export/download/retention readers move to rows; JSON scanner helpers are deleted. |
| Artifact file metadata | `backend/src/intric/database/tables/files_table.py:14-22` | Export currently trusts payload metadata instead of file rows. | `Files` joined from result-file rows. | Manifest and summaries derive checksum/size/mimetype/file type from `Files`. |
| Signed artifact eligibility | `backend/src/intric/flows/application/flow_run_service.py:762-786` scans `output_payload_json`. | Payload JSON can drift from rows and cannot represent purged content cleanly. | `FlowRunRepository.get_result_file()` plus `FileRepository.get_by_id()`. | No JSON fallback; row-missing and content-purged states are distinct. |
| Artifact retention file set | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:560-727` scans/prunes JSON references. | Retention currently depends on the display payload it is supposed to prune. | `FlowRunStepResultFiles` joined to `Files`. | `_extract_generated_file_ids()` is deleted; `_prune_generated_artifact_payload()` remains only until 7A.7 removes display payload keys. |
| Evidence artifact summary | `backend/src/intric/flows/flow_run_export_json.py:281-293`, `backend/src/intric/flows/flow_run_export_json.py:636-720` | Summary and manifest are payload-derived and under-report purged rows. | `bundle.result_files`, built from canonical rows. | Payload-derived artifact functions and `payload_derived` manifest state are deleted. |

### Row Semantics

1. `FlowRunStepResultFiles.ordinal` is set at write time and is canonical. `list_result_files()` orders by `step_order`, `attempt_no`, then `ordinal`.
2. The current writer makes ordinal deterministic from sorted UUID order. 7A.6 does not change writer order; if the UI later needs authoring order, that belongs with the 7A.7 display rewrite.
3. If a file id appears in both `generated_file_ids` and `artifacts`, the canonical source is `declared_artifact`; this preserves the current consumer-facing source decision.
4. Summary-level `artifacts_count` deduplicates by `file_id` across all attempts.
5. Step overview artifact details use the latest attempt per step (`max(attempt_no)`), so a retried step does not double-display stale attempt artifacts.
6. Final-output artifact details use the latest attempt from the terminal step represented in `result_files`. If no result-file row exists for that step, final output reports no artifacts even if display payload keys remain.
7. Availability is `available` only when `Files.blob` or `Files.text` is present. `Files.transcription` is not downloadable artifact content.
8. `bundle.result_files` is part of the content hash input. Manifest summaries are typed derived metadata, not part of the hash input except through their source rows in the bundle.

### Expected Source/Test Changes For 7A.6

- Add a narrow `FlowRunStepResultFile` projection model with result-file row fields, file metadata, and `availability`.
- Add `FlowRunRepository.list_result_files()` and `FlowRunRepository.get_result_file()` row-backed queries.
- Add a `ResourceGoneException`/410 mapping if no existing domain exception supports Gone without raising FastAPI `HTTPException` from application code.
- Move `FlowRunService.get_run_artifact_file()` to the row-backed lookup. Re-read file content through `FileRepository.get_by_id()` and verify content is still present before signing.
- Add `result_files` to `EvidenceBundle`, `RedactedEvidenceBundle`, `FlowRunEvidenceResponse`, and export bundle payloads.
- Replace artifact summary/detail builders in `flow_run_export_json.py` and `flow_run_evidence.py` with result-file-derived builders.
- Replace `EvidenceArtifactAvailabilitySummary.tracking_state="payload_derived"` with typed `"tracked"` fields.
- Move generated artifact retention cleanup to result-file rows. Delete `_extract_generated_file_ids()`.
- Delete `_reconcile_missing_generated_artifact_references()` unless implementation proves a row-backed failure mode that retention itself does not already cover transactionally.
- Update OpenAPI examples and contract tests for `result_files`, row-backed manifest fields, and 410 artifact errors.

### Required Tests

- Repository integration:
  - `list_result_files()` returns all attempts ordered by `step_order`, `attempt_no`, `ordinal`.
  - `get_result_file()` is tenant-scoped and returns no row across tenants.
  - availability is `available` for blob/text content and `content_purged` when blob/text are both null.
- Service/unit:
  - JSON payload artifact references are ignored when no result-file row exists.
  - row-backed artifacts return a signed-file candidate.
  - content-purged rows raise `flow_run_artifact_content_unavailable`.
  - file content cleared between result-row lookup and file fetch does not produce a signed URL.
- Export/unit:
  - manifest artifact availability fields are explicit typed fields, not `extra`.
  - `bundle.result_files` is included in the hashed bundle payload.
  - summaries, final output, and step overview use row-backed details and latest-attempt display rules.
- Retention/integration:
  - cleanup clears `Files` content and appends tombstones from result-file rows even when display payload artifact keys are absent.
  - second cleanup is idempotent.
  - if the row-backed reconciler is deleted, no test preserves it as a compatibility path.
- Guards:
  - `rg -n "payload-derived artifact references|payload_artifact_count|_extract_generated_file_ids|_collect_artifact_ids" backend/src backend/tests` should find no live source/test owner.
  - staged diff contains no process comments, Claude/Codex references in source, deprecated Flow compatibility paths, or comments that restate code.

### Claude Plan Review Reconciliation

Claude iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, `MIN_SCORE: 6`.

Accepted before implementation:

- Use 410 for known artifacts whose content was purged, with a distinct machine-readable code.
- Pin availability as blob/text-only and re-validate file content after the row lookup before signing.
- Delete the reconciler unless a real post-7A.6 failure mode exists.
- Define JSON artifact keys as frontend display payload with an explicit 7A.7 deletion condition.
- Pin row ordering, duplicate source precedence, latest-attempt display, and final-output derivation rules.
- Declare all new manifest fields in typed models.
- Keep `result_files` in the hashed bundle payload and document deterministic ordering.
- Add inverse tests proving JSON payload artifact references are ignored.

Proceed only after the same Claude session returns green light for the revised implementation or Codex documents any remaining disagreement with file:line evidence.

## Scope For 7A.5

### Goals

- Destructive retention cleanup writes reviewable tombstones instead of silently erasing evidence/provenance/artifact content.
- Evidence export manifest reports tracked retention state and counts when tombstones are present.
- Evidence export bundle distinguishes available, retention-purged, and artifact-content-purged states where this slice has evidence. `redacted_for_deletion_count` remains explicit and zero until tenant/DSAR deletion markers exist.
- Exact raw prompt/completion retention remains rejected in this slice; evidence stays preview+hash unless a later retention/deletion design approves exact raw retention.
- Flow/Flow AI Builder is still unreleased, so this slice removes the 7A.4 public `FlowRunStepPublic.tool_calls_metadata` deprecation surface instead of preserving a deprecated Flow compatibility field.
- Use existing canonical owners first:
  - `FlowStepAttempts.provenance_json` for attempt-provenance retention markers
  - `FlowStepResults.output_payload_json` for step-result/debug/artifact retention markers
  - `Files` rows for artifact content state, with file content cleared by existing cleanup

### Non-Goals

- No new table, migration, broad evidence ledger, or parallel evidence system.
- No exact raw prompt/completion byte retention.
- No tenant/DSAR deletion feature beyond markers for current retention cleanup.
- No artifact/file ownership migration; 7A.6 owns canonical `FlowRunStepResultFiles` + `Files` export/download ownership.
- No frontend evidence UI/view-model rewrite; 7A.7 owns frontend evidence alignment.
- No Batch 8 rerun behavior, Batch 9 human review behavior, package rename, or `intric.*` namespace migration.

### Inventory

| concept | current locations | shipped/persisted data need? | keep/delete/rewrite | canonical owner | deletion condition |
|---|---|---|---|---|---|
| Debug evidence cleanup | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:387-456` | No shipped Flow users, but current cleanup destroys prompt/input/model/tool/provenance content. | Rewrite to write tombstones while clearing sensitive fields. | `DataRetentionService` executes cleanup; tombstone value object owns marker shape. | Later migration/table only if existing owners cannot scale. |
| Attempt provenance purge | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:438-448` | Current behavior sets `FlowStepAttempts.provenance_json=None`, losing reviewability. | Replace with typed retention marker in `FlowStepAttempts.provenance_json`. | Attempt row remains the owner for attempt-level provenance availability. | Marker can be migrated to a table only with human-approved data-model decision. |
| Step-result debug purge | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:399-436` | Current behavior clears debug fields and prunes output payload without a durable marker. | Append typed tombstone marker to `FlowStepResults.output_payload_json`. | Step result row remains the owner for result-level debug payload availability. | 7A.6 may move artifact-specific marker ownership when file rows become canonical. |
| Artifact content purge | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:458-523` | Current behavior clears `Files.blob/text/transcription` and prunes generated artifact references. | Append typed tombstone marker with file ids before pruning references. | Step result output payload records artifact purge until 7A.6 normalizes file evidence ownership. | 7A.6 can replace payload-derived artifact marker with file-row ownership. |
| Missing-artifact reconciler | `backend/src/intric/data_retention/infrastructure/data_retention_service.py:525-596` | Current reconciler scans non-null step-result payloads and prunes missing generated artifact references. | Preserve retention tombstones and skip tombstone-only rows. | `DataRetentionService` owns destructive retention/reconciliation mutation behavior. | 7A.6 may replace payload scanning with canonical file/result-file rows. |
| Attempt provenance parser | `backend/src/intric/flows/flow_run_provenance.py:243-321` | Parser currently treats any non-current provenance schema as corrupt. | Add explicit retention-purged parse status and marker branch. | `flow_run_provenance.py` owns attempt provenance JSON parsing. | None. |
| Provenance manifest status | `backend/src/intric/flows/flow_run_evidence_export_manifest.py:14-17` | Manifest status is a closed `not_tracked/tracked/corrupt` literal. | Extend typed status to include retention-purged state. | Export manifest model owns public evidence contract. | 7A.7 owns frontend generated schema alignment if this backend schema is consumed in UI. |
| Evidence export retention summary | `backend/src/intric/flows/flow_run_export_json.py:174-180` | Manifest currently always says retention tombstone tracking is `not_tracked`. | Rewrite summary to derive counts from tombstones in bundle payloads. | `flow_run_export_json.py` owns export manifest summary. | None. |

### Planned Shape

1. Add a narrow typed tombstone value object, preferably `backend/src/intric/flows/flow_retention_tombstone.py`.
   - It is not a ledger and has no persistence of its own.
   - It only defines marker schema/version, payload-key constants, parser helpers, and helper builders.
   - Use explicit schema versions:
     - `flow-retention-tombstone.v1` for the tombstone payload.
     - `flow-attempt-retention-marker.v1` for the attempt-level retention wrapper stored in `FlowStepAttempts.provenance_json`.
   - Use explicit status literals:
     - `FlowAttemptProvenanceParseStatus`: add `retention_purged`.
     - `EvidenceProvenancePersistedVersionStatus`: add `retention_purged`.
     - `EvidenceRetentionTrackingState` stays `not_tracked | tracked`; any current-version tombstone makes the retention summary tracked.
   - Use the namespaced output payload key `flow_retention_tombstones` for `FlowStepResults.output_payload_json`; prove zero collision with current writers before implementation.
   - Required marker fields: schema version, tenant id, run id, trace id, data class, object type/id, policy source, cutoff, actor/source, counts, timestamp, and retention state.
   - `counts` is a typed per-marker map of logical objects made unavailable by the marker. Examples: debug cleanup records cleared field count and pruned output-key count; artifact cleanup records referenced generated file count. It is not the batch job's row count.
   - Marker actor/source must be system-level and PII-free, for example `data_retention_worker`; do not write user ids into tombstones in this slice.
   - Define the actor/source as one constant in `flow_retention_tombstone.py`, not repeated strings.
2. Thread per-run cleanup context through `cleanup_old_flow_runtime_data()` instead of losing run metadata in bare `set[UUID]` collections.
   - Include tenant id, run id, trace id, policy source, cutoff, and cleanup timestamp.
   - Select `FlowRuns.tenant_id`, `FlowRuns.trace_id`, and the effective cutoff context in `_iter_flow_run_retention_rows()`.
   - Use row-level Python updates for the affected rows in this slice. This favors explicit idempotency and marker shape over clever SQL JSON construction; the existing batch size still bounds rows, and performance risk is documented for later table normalization if needed.
3. Change debug cleanup:
   - clear sensitive step-result fields as today
   - replace attempt `provenance_json=None` with an attempt-level retention marker
   - append a step-result output tombstone before pruning debug-only payload keys
   - no-op when the current-version marker already exists, so a second cleanup pass does not mutate timestamps or inflate counts
4. Change artifact cleanup:
   - collect generated file ids before pruning
   - append an artifact-content tombstone to `FlowStepResults.output_payload_json`
   - continue clearing `Files.blob`, `Files.text`, and `Files.transcription` as today
   - no-op when the current-version marker already exists for the same data class/object id
   - update `_reconcile_missing_generated_artifact_references()` to preserve tombstones and skip tombstone-only payloads
5. Update evidence export:
   - manifest `retention_state_summary.tracking_state` becomes `tracked` when markers exist
   - counts include tombstones, `retention_purged`, and `artifact_content_purged`
   - `redacted_for_deletion_count` remains explicit and `0` in this slice because tenant/DSAR deletion markers are not implemented here
   - retention summary `note` is derived from the actual state and counts, not a stale static fallback string
   - bundle attempts with retention marker parse as retention-purged, not corrupt provenance
   - provenance status precedence is `corrupt > retention_purged > tracked > not_tracked`
   - RAG tracking state handles retention-purged attempts explicitly:
     - ordered precedence is `unknown_corrupt > partial_corrupt > tracked_with_sources > tracked_no_sources > retention_purged > not_tracked`
     - all attempts retention-purged and none corrupt or tracked: `retention_purged`
     - tracked RAG payloads plus retention markers: keep the tracked state (`tracked_with_sources` or `tracked_no_sources`) and include `retention_purged_attempt_count`
     - corrupt plus retention markers and no tracked RAG payloads: `unknown_corrupt`
     - corrupt plus tracked RAG payloads, with or without retention markers: `partial_corrupt`
   - `FlowAttemptProvenanceParseResult.to_export_payload()` returns the retention marker payload for `retention_purged`, same as it returns provenance for `tracked` and corruption marker payload for `corrupt`.
6. Reject exact raw prompt/completion retention in this slice and document why: current evidence uses preview+hash and retained output payloads; exact raw bytes are not stored until a deletion/DSAR contract proves hard-delete or key-shred behavior.
7. Do not attempt to backfill rows already purged to `None` before this slice. Document the ambiguity as carry-forward: those rows remain indistinguishable from never-tracked attempts until a human-approved backfill/migration exists.
8. Carry forward a possible future `flow-attempt-payload-envelope.v1` discriminated union if more persisted attempt-state schemas are added. This slice uses distinct schema-version discriminators to avoid a migration, but the three-schema-in-one-column shape should not grow indefinitely.

### Behavior Pins Before And With Changes

- Current cleanup clears sensitive debug fields and generated artifact content.
- Cleanup writes tombstones with tenant id, run id, trace id, data class, object type/id, policy source, cutoff, actor/source, counts, timestamp, and retention state.
- Attempt provenance retention markers export as retention-purged, not corrupt provenance.
- A second cleanup pass is a no-op for current-version tombstones and returns zero changed debug/artifact counts.
- Evidence manifest retention summary reports tracked counts when markers are present.
- Artifact content purge remains visible after generated artifact references are pruned.
- Missing-artifact reconciliation preserves tombstones and ignores tombstone-only payloads.
- Redacted exports preserve PII-free tombstone fields.
- Mixed provenance status precedence is pinned: corrupt beats retention-purged, retention-purged beats tracked, tracked beats not-tracked.
- RAG tracking reports post-7A.5 retention purge honestly instead of conflating it with never-tracked evidence.
- No exact raw prompt/completion payload is stored by this slice.
- `FlowRunStepPublic` no longer exposes result-level `tool_calls_metadata`; Flow evidence tool-call payloads live in attempt provenance.

### Required Test Cases For 7A.5

1. `FlowStepAttempts.provenance_json` retention marker parses as `retention_purged`, not `corrupt`.
2. Manifest precedence with one corrupt attempt and one retention-purged attempt returns `provenance_persisted_version_status == "corrupt"` while `retention_state_summary.tombstone_count > 0`.
3. Manifest precedence with one retention-purged attempt and one tracked attempt returns `provenance_persisted_version_status == "retention_purged"` and keeps tracked payload details in the bundle.
4. Two consecutive `cleanup_old_flow_runtime_data()` calls are idempotent: the second pass returns zero `debug_step_results`, `debug_step_attempts`, `generated_artifact_rows`, and `generated_artifact_files`.
5. `_reconcile_missing_generated_artifact_references()` skips tombstone-only `output_payload_json` and preserves tombstones when re-pruning a row that still has generated artifact references.
6. Marker actor/source is the single constant `data_retention_worker`, and no user id is written into tombstone payloads.
7. Redacted export preserves marker fields.
8. HTTP evidence export pins corrupt plus tombstone precedence through the public endpoint.
9. RAG tracking returns `retention_purged` when every attempt is retention-purged and none are corrupt or tracked.
10. RAG tracking returns tracked states with `retention_purged_attempt_count` when tracked RAG payloads and retention markers coexist.
11. RAG tracking returns `unknown_corrupt` for corrupt plus retention markers with no tracked RAG payloads, and `partial_corrupt` when a tracked RAG payload also exists.
12. The pre-implementation marker collision grep returns no existing source/test writers.
13. OpenAPI contract tests pin `retention_purged` in the evidence manifest persisted-version status enum.
14. Retention summary note derivation is deterministic: identical state/counts produce identical notes, and tracked tombstone state produces a different note than `not_tracked`.
15. Invalid attempt retention markers parse as corrupt with `flow_attempt_provenance_invalid_retention_marker`.
16. OpenAPI pins absence of public result-level `tool_calls_metadata` instead of a deprecated Flow compatibility field.

### Collision And Compatibility Checks

Before implementation, run:

```bash
rg -n "flow_retention_tombstones|flow-retention-tombstone|flow-attempt-retention-marker" backend/src backend/tests
```

Expected before the slice: no source/test writers. If this finds a real existing writer, stop and choose a different marker key/schema version in the plan before implementation.

Pre-7A.5 rows already purged to `provenance_json=None` or already-pruned `output_payload_json` remain `not_tracked` in exports. This is known carry-forward debt, not a silent success state. A one-shot backfill marker is a future migration/data decision, not part of this no-migration slice.

Full result-level `tool_calls_metadata` deletion remains a PRD-008 / Batch 10 cleanup item after Batch 7A finishes the evidence foundation: delete `FlowStepResult.tool_calls_metadata`, the database column, repository persistence slot, runtime write/read slots, generated schema drift, tests for the removed field, and `_RESULT_FIELDS_REPLACED_BY_ATTEMPT_PROVENANCE` in one deliberate slice. 7A.5 removes the public `FlowRunStepPublic` field but does not start that wider persisted-shape cleanup.

### Expected Source/Test Changes For 7A.5

Expected source:

- `backend/.importlinter`
- `backend/src/intric/flows/flow_retention_tombstone.py`
- `backend/src/intric/data_retention/infrastructure/data_retention_service.py`
- `backend/src/intric/flows/flow_run_provenance.py`
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
- `backend/src/intric/flows/flow_run_export_json.py`
- `backend/src/intric/flows/flow_run_evidence_export_manifest.py`
- `backend/src/intric/flows/api/flow_models.py` if the OpenAPI evidence-export example needs status/count updates

Expected tests:

- `backend/tests/integration/test_flow_runtime_retention_cleanup.py`
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` if HTTP evidence export needs a public pin
- `backend/tests/unit/test_flow_openapi_contract.py` if the manifest status enum/example changes the public contract
- `backend/tests/unittests/flows/test_flow_router.py` if the router contract example changes with the manifest example
- `backend/tests/unittests/flows/test_flow_models.py` if the public Flow step model removes result-level tool-call metadata

Expected docs:

- `docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-6.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-6.md`

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- migrations
- frontend evidence UI
- `frontend/packages/intric-js/src/types/schema.d.ts`; 7A.7 owns generated/frontend evidence type alignment if the backend schema change is consumed there
- package names or `intric.*` namespace paths

### Validation Commands For 7A.5

```bash
cd backend && uv run pytest \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_models.py \
  -q
```

```bash
cd backend && POSTGRES_HOST=placeholder uv run pytest \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_with_retention_tombstone \
  -q
```

`POSTGRES_HOST=placeholder` is the local/testcontainers fallback for the HTTP evidence pins when the long-running app container cannot be used from Codex and local Redis/Postgres services are not available.

```bash
cd backend && uv run pyright \
  src/intric/flows/flow_retention_tombstone.py \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_evidence_export_manifest.py \
  src/intric/flows/api/flow_models.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_models.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/flow_retention_tombstone.py \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_evidence_export_manifest.py \
  src/intric/flows/api/flow_models.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_models.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/flow_retention_tombstone.py \
  src/intric/data_retention/infrastructure/data_retention_service.py \
  src/intric/flows/flow_run_provenance.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  src/intric/flows/flow_run_evidence_export_manifest.py \
  src/intric/flows/api/flow_models.py \
  tests/integration/test_flow_runtime_retention_cleanup.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py \
  tests/unittests/flows/test_flow_router.py \
  tests/unittests/flows/test_flow_models.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
rg -n "flow_retention_tombstones|flow-retention-tombstone|flow-attempt-retention-marker" backend/src backend/tests
```

```bash
rg -n "provenance_json=None|retention_state_summary=EvidenceRetentionStateSummary\\(\\s*tracking_state=\"not_tracked\"|Batch 7A|7A\\.|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)" \
  backend/src/intric/data_retention/infrastructure/data_retention_service.py \
  backend/src/intric/flows/flow_retention_tombstone.py \
  backend/src/intric/flows/flow_run_provenance.py \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/flow_run_evidence_export_manifest.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/tests/integration/test_flow_runtime_retention_cleanup.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  backend/tests/unittests/flows/test_flow_router.py \
  backend/tests/unittests/flows/test_flow_models.py
```

```bash
git diff --check -- \
  backend/.importlinter \
  backend/src/intric/flows/flow_retention_tombstone.py \
  backend/src/intric/data_retention/infrastructure/data_retention_service.py \
  backend/src/intric/flows/flow_run_provenance.py \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/src/intric/flows/flow_run_evidence_export_manifest.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/tests/integration/test_flow_runtime_retention_cleanup.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unittests/flows/test_flow_router.py \
  backend/tests/unittests/flows/test_flow_models.py \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-6.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-6.md
```

## Scope For 7A.4

### Goals

- Treat attempt provenance as the evidence export source of truth for tool-call payloads.
- Stop new runtime-completed step results from duplicating tool calls into `FlowStepResult.tool_calls_metadata`.
- Ensure evidence export bundles do not expose step-result `tool_calls_metadata` as a second tool-call source.
- Distinguish knowledge/RAG evidence states: `not_tracked`, `tracked_no_sources`, `tracked_with_sources`, `partial_corrupt`, and `unknown_corrupt`.
- Keep RAG summary text truthful: absence of sources must not imply no knowledge was used when tracking did not happen.
- Avoid schema/data migrations in this slice. Column deletion is a separate human-approved migration decision after readers/writers stop relying on the field.

### Non-Goals

- No migration or table/column deletion.
- No raw prompt/completion retention.
- No retention tombstones; 7A.5 owns tombstone storage and deletion semantics.
- No artifact/file ownership migration; 7A.6 owns `FlowRunStepResultFiles` + `Files` canonical export.
- No frontend evidence UI/view-model rewrite; 7A.7 owns frontend evidence alignment if backend schemas change.
- No Batch 8 rerun behavior, Batch 9 human review behavior, package rename, or `intric.*` namespace migration.

### Inventory

| concept | current locations | shipped/persisted data need? | keep/delete/rewrite | canonical owner | deletion condition |
|---|---|---|---|---|---|
| Runtime tool-call source | `backend/src/intric/flows/runtime/step_execution_runtime.py:909-910`, `backend/src/intric/flows/runtime/executor.py:187-189` | Runtime completion currently captures provider tool calls once, then 7A.3 writes them into attempt provenance. | Keep writer into `StepExecutionOutput`, keep attempt provenance write. | `FlowStepAttempts.provenance_json.llm.tool_calls` via `flow_run_provenance.py` | None; this is the canonical evidence path. |
| Step-result tool-call duplicate | `backend/src/intric/flows/runtime/step_result_builder.py:90`, `backend/src/intric/flows/domain/flow.py:170`, `backend/src/intric/flows/api/flow_models.py:536`, `backend/src/intric/flows/infrastructure/flow_repo.py:542` | No shipped Flow users. The DB/API field may exist for branch-local persisted rows and tests. | Stop new runtime writes and hide it from evidence export bundles; do not migrate/delete column in this slice. | Attempt provenance. | Human-approved migration removes DB/API field after reader audit and row proof. |
| Public result tool-call read field | `backend/src/intric/flows/api/flow_models.py:536`, `backend/tests/unittests/flows/test_flow_models.py:186`, `backend/tests/unittests/flows/test_flow_models.py:331`, generated schema from the OpenAPI contract | No shipped Flow users, but the API/read model exists and current tests pin it. | Keep field as a Tier B public/read-model compatibility surface, mark deprecated, and point evidence readers to attempt provenance. | Attempt provenance for evidence; public result field remains a temporary read surface. | Human-approved API/schema migration removes it after SDK/frontend reader audit. |
| Evidence export result dumping | `backend/src/intric/flows/flow_run_evidence_bundle.py:119-123` | Export currently serializes `FlowStepResult` as-is, so old/result fixture tool calls can appear beside attempt provenance. | Rewrite `_dump_result_record` to omit `tool_calls_metadata` in export payloads. | Attempt provenance in `step_attempts[].provenance_json.llm.tool_calls`. | Migration can delete the result field later. |
| RAG default tracking | `backend/src/intric/flows/flow_run_provenance.py:183-194`, `backend/src/intric/flows/flow_run_export_json.py:323-338` | Current no-RAG path returns defaults with `retrieval_tracked=True`, which can imply tracking happened. | Add explicit export summary states. Use tracked defaults only when a RAG section exists. | `flow_run_export_json.py` export summary; `flow_run_provenance.py` normalizes per-attempt RAG payloads. | 7A.7 can expose typed frontend view-model states if needed. |
| RAG sources | `backend/src/intric/flows/flow_run_export_json.py:272-320` | Sources are export evidence when provenance has references. | Keep source collection, add state derived from sources/tracking. | Attempt provenance RAG section. | None. |

### Boundary Asymmetry

7A.4 intentionally migrates the write side and evidence export side, but not the whole persisted/public API surface. New runtime writes stop populating `FlowStepResult.tool_calls_metadata`, and evidence exports omit result-level tool calls so tool-call evidence has one export owner: attempt provenance. The database column, repository persistence slot, API model field, and generated schema field remain for this slice as Tier B public/persisted readers. They must be marked deprecated, not silently deleted, because removal is a separate schema/API migration decision.

### RAG Tracking State Precedence

Run-level `summary.rag_usage_tracking.tracking_state` is derived from typed attempt provenance parse results, not by scanning only the serialized bundle payload. Precedence is:

| precedence | state | condition |
|---|---|---|
| 1 | `unknown_corrupt` | Every relevant provenance signal is corrupt or absent and at least one attempt provenance parse result is corrupt. |
| 2 | `partial_corrupt` | At least one attempt is corrupt and at least one valid current attempt has a RAG section. |
| 3 | `tracked_with_sources` | At least one valid current attempt has a RAG section with source references and no corrupt attempt is present. |
| 4 | `tracked_no_sources` | At least one valid current attempt has a RAG section, but no source references are present and no corrupt attempt is present. |
| 5 | `not_tracked` | No valid current attempt has a RAG section and no corrupt attempt is present. |

The per-attempt RAG normalizer keeps the current `default_rag_tracking()` behavior for actual RAG sections. Export-summary fallback uses a distinct untracked summary so absence of RAG provenance is never confused with tracked retrieval that found no sources.

### Planned Shape

1. Add `derive_rag_usage_tracking()` in `flow_run_export_json.py`. It takes both `bundle_payload` and `provenance_parse_results` and applies the precedence table above.
2. Add `tracking_state` to `summary["rag_usage_tracking"]` while preserving existing boolean fields for current UI/API consumers.
3. Add `untracked_rag_summary()` for the no-RAG default summary. It returns `tracking_state="not_tracked"` and `retrieval_tracked=False` with a note that absence of sources does not prove knowledge was unused.
4. Preserve `default_rag_tracking()` for actual RAG sections; a RAG section without explicit tracking remains tracked evidence with zero sources.
5. Change `build_completed_step_result` so new completed results no longer copy `output.tool_calls_metadata` into `FlowStepResult.tool_calls_metadata`.
6. Change evidence export result dumping so `bundle.step_results[*].tool_calls_metadata` is absent. Tool-call evidence lives in `bundle.step_attempts[*].provenance_json.llm.tool_calls`.
7. Mark `FlowRunStepPublic.tool_calls_metadata` deprecated with a description that identifies attempt provenance as the evidence owner. Add an OpenAPI assertion so the deprecation signal stays visible to generated-client consumers.
8. Do not delete the DB/API field in this slice. That deletion requires a schema/API migration decision and should happen only after this slice proves no current export/runtime reader depends on result-level tool calls.
9. Audit data-retention cleanup only for regression risk: `backend/src/intric/data_retention/infrastructure/data_retention_service.py:411-422` still updates rows when non-tool debug fields are present or output payload pruning changes the payload, so no retention cleanup source change is planned.
10. Carry forward a deletion trigger: remove `FlowRunStepPublic.tool_calls_metadata` and the database column only after a human-approved SDK/frontend reader audit and persisted-row proof show zero required readers or a migration/backfill plan exists.

### Behavior Pins Before And With Changes

- Runtime completion with tool calls still records tool-call evidence in attempt provenance.
- Completed step results created by the runtime no longer carry result-level `tool_calls_metadata`.
- Evidence export bundles omit result-level `tool_calls_metadata` as a second source, including when old branch-local result rows contain populated tool-call metadata.
- Evidence export summary reports `not_tracked` when no RAG provenance exists and does not imply knowledge was unused.
- Evidence export summary reports `tracked_no_sources` for tracked RAG provenance with no references.
- Evidence export summary reports `tracked_with_sources` for tracked RAG provenance with references.
- Evidence export summary reports `unknown_corrupt` when corrupt attempt provenance is the only available signal.
- Evidence export summary reports `partial_corrupt` when valid RAG evidence and corrupt attempt provenance coexist.
- Mixed attempts follow precedence: unknown-corrupt/partial-corrupt beats tracked-with-sources, tracked-with-sources beats tracked-no-sources, tracked-no-sources beats not-tracked.
- OpenAPI marks the surviving public `tool_calls_metadata` result field as deprecated.
- Existing RAG display/source summaries remain stable for tracked RAG with sources.

Required test cases:

- no provenance yields `not_tracked`
- all valid current attempts have RAG sections with zero sources yields `tracked_no_sources`
- at least one valid current attempt has RAG sources yields `tracked_with_sources`
- any corrupt attempt mixed with tracked-with-sources yields `partial_corrupt`
- all corrupt attempts yield `unknown_corrupt` with `retrieval_tracked=False`
- mixed tracked-no-sources and tracked-with-sources yields `tracked_with_sources`
- old branch-local result row with `step_results[i].tool_calls_metadata=[...]` and attempt provenance `llm.tool_calls` yields no `tool_calls_metadata` key in `bundle.step_results[i]` while preserving `bundle.step_attempts[i].provenance_json.llm.tool_calls`
- OpenAPI exposes `FlowRunStepPublic.properties.tool_calls_metadata.deprecated is true` and the description points evidence consumers to attempt provenance

### Expected Source/Test Changes For 7A.4

Expected source:

- `backend/src/intric/flows/runtime/step_result_builder.py`
- `backend/src/intric/flows/flow_run_evidence_bundle.py`
- `backend/src/intric/flows/flow_run_export_json.py`
- `backend/src/intric/flows/api/flow_models.py`

Expected tests:

- `backend/tests/unittests/flows/test_flow_runtime_builders.py`
- `backend/tests/unittests/flows/test_flow_run_evidence.py`
- `backend/tests/unittests/flows/test_step_attempt_runtime.py` if tool-call provenance coverage needs a focused assertion
- `backend/tests/integration/flows/test_flow_evidence_api_contracts.py` if HTTP export summary shape changes need a public pin
- `backend/tests/unit/test_flow_openapi_contract.py`

Expected docs:

- `docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/retrospective-5.md`
- `docs/refactor/execution/batch-7a-evidence-provenance-contract/claude-reconciliation-5.md`

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- migrations
- frontend evidence UI
- package names or `intric.*` namespace paths

### Validation Commands For 7A.4

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/unittests/flows/test_flow_runtime_builders.py \
  tests/unittests/flows/test_step_attempt_runtime.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_returns_redacted_json_attachment \
  tests/integration/flows/test_flow_evidence_api_contracts.py::test_flow_run_evidence_export_marks_corrupt_attempt_provenance \
  tests/unit/test_flow_openapi_contract.py \
  -q
```

```bash
cd backend && uv run pyright \
  src/intric/flows/runtime/step_result_builder.py \
  src/intric/flows/api/flow_models.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  tests/unittests/flows/test_flow_runtime_builders.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run ruff check \
  src/intric/flows/runtime/step_result_builder.py \
  src/intric/flows/api/flow_models.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  tests/unittests/flows/test_flow_runtime_builders.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/runtime/step_result_builder.py \
  src/intric/flows/api/flow_models.py \
  src/intric/flows/flow_run_evidence_bundle.py \
  src/intric/flows/flow_run_export_json.py \
  tests/unittests/flows/test_flow_runtime_builders.py \
  tests/unittests/flows/test_flow_run_evidence.py \
  tests/integration/flows/test_flow_evidence_api_contracts.py \
  tests/unit/test_flow_openapi_contract.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
rg -n "tool_calls_metadata=output\\.tool_calls_metadata|retrieval_tracked=True.*not_tracked|retrieval_tracked.*True.*not tracked|Batch 7A|7A\\.|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)" \
  backend/src/intric/flows/runtime/step_result_builder.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/tests/unittests/flows/test_flow_runtime_builders.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unit/test_flow_openapi_contract.py
```

```bash
git diff --check -- \
  backend/src/intric/flows/runtime/step_result_builder.py \
  backend/src/intric/flows/api/flow_models.py \
  backend/src/intric/flows/flow_run_evidence_bundle.py \
  backend/src/intric/flows/flow_run_export_json.py \
  backend/tests/unittests/flows/test_flow_runtime_builders.py \
  backend/tests/unittests/flows/test_flow_run_evidence.py \
  backend/tests/integration/flows/test_flow_evidence_api_contracts.py \
  backend/tests/unit/test_flow_openapi_contract.py \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/plan.md \
  docs/refactor/execution/batch-7a-evidence-provenance-contract/journal.md
```

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
