# Batch 7A — Evidence / Provenance Contract Foundation

## Active Next Plan

The active implementation slice is **7A.1 — Evidence inventory, dead-code/dead-test cleanup, and behavior pins**.

Official Batch 8 step rerun does not start until this inserted evidence/provenance foundation reaches a stable checkpoint. This plan is limited to the first slice: measured inventory, deletion/rewrite decisions for clearly dead evidence compatibility, and behavior pins for the current evidence API/export contract.

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
