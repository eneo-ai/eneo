# Phase 1a Agent D: Dead Code And Legacy Review

TL;DR:
1. The highest-confidence dead code is not the large runtime code; it is small compatibility surface that keeps parallel import/export paths alive.
2. Immediate delete candidates are the unused frontend redispatch alias, test-only router callable re-exports, and the unused `normalize_legacy_config` function after a DB shape check.
3. Several legacy paths are not safe one-line deletes because they protect persisted row shapes: DOCX `template_file_id`, legacy form field types, legacy mirrored input templates, and flow-run principal identity.
4. Top-level run `file_ids` is a public API contract, not just an internal shim; deleting it must update OpenAPI, `intric-js`, idempotency, examples, and contract tests.
5. Overall score is 4/10, driven by single-source-of-truth risk across file mapping, template assets, and principal identity.

## Scope And Method

This review is documentation-only and is limited to shims, compatibility paths, duplicate exports, dead tests, fallback/repair/legacy paths, unused files/symbols, and deletion opportunities across the flow runtime, AI Builder, frontend flow UI, tests, and relevant migrations.

Standards applied:

| Standard | Evidence | How this review applies it |
|---|---|---|
| Canonical ownership | `docs/engineering/maintainability-standards.md:40-58` | Every shim and re-export is treated as a possible parallel owner unless it has a real stable boundary. |
| Delete-first refactoring | `docs/engineering/maintainability-standards.md:71-85` | Deletion is preferred for never-shipped compatibility, wrappers, and tests that protect bad architecture. |
| Behavior-focused tests | `docs/engineering/testing-standard.md:3-24` | Tests that only preserve import identity or compatibility shims are delete/rewrite candidates. |
| Comment standard | `docs/engineering/comment-and-readability-standard.md:5-25` | Comments that claim compatibility without current importers are defects. |
| API contract review | `docs/engineering/api-design-standard.md:7-18`, `docs/engineering/api-design-standard.md:38-47` | Public request fields such as `file_ids` require generated-client and contract-test migration, not source-only deletion. |
| Frontend state ownership | `docs/engineering/frontend-state-standard.md:3-18` | Legacy `$effect` cleanup paths are flagged when they mutate state to compensate for old persisted data. |

Peer review: Claude iteration 1 returned `changes_required` and correctly challenged several deletion claims that needed migration gates. Verified changes are incorporated below. Artifact: `.codex/artifacts/claude-peer-loop-phase-1-agent-d-dead-code-deletion-direction-20260428T181638Z.md`.

## Delete / Keep / Migrate Summary

| Item | Verdict | Current owner | Proposed canonical home | Delete / migrate path | Confidence |
|---|---|---|---|---|---|
| Backend flow compatibility shims: `flow_repo.py`, `flow_version_repo.py`, `flow_service.py`, `flow_run_repo.py`, `flow_dispatch.py` | Migrate then delete | Per-file shim modules | `intric.flows.application`, `intric.flows.infrastructure`, and `intric.flows.domain` modules | Rewrite imports, update `_LAZY_EXPORTS`, update `.importlinter`, delete shim identity tests. | High |
| `backend/src/intric/flows/flow.py` domain shim | Migrate then delete | `intric.flows.flow` | `intric.flows.domain.flow` | Rewrite production AI Builder imports first; delete only after zero production imports. | High |
| `backend/src/intric/flows/flow_run_service.py` subclass shim | Fix tests then delete | Shim subclass | `intric.flows.application.flow_run_service.FlowRunService` | Retarget imports and logger patches to canonical module; remove subclass. | High |
| `backend/src/intric/flows/flow_template_validation.py` | Replace with boundary rule, then delete | Compatibility re-export | `intric.files.docx_template_validation` plus import-linter rule | Add a contract preventing flow validator cycles, keep startup smoke test, then remove module if zero importers. | Medium |
| `flow_consumer_router.py` / `flow_run_router.py` endpoint callable re-exports | Delete/rewrite | Router aggregators | Concrete endpoint modules plus router-only assembly | Remove callable re-exports and replace identity test with import-boundary rule. | High |
| `normalize_legacy_config` | DB-check then delete | `http_transport.normalizer` | No canonical home if DB contains no legacy HTTP configs | Verify no persisted HTTP config lacks `auth`; delete function and tests if zero. | Medium |
| Legacy DOCX `template_file_id` support | Backfill then delete | Backend service, upload contract, frontend template config | `flow_template_assets` and `template_asset_id` | Backfill rows, prove zero `template_file_id`-only configs, delete backend/frontend fallbacks. | Medium |
| Top-level run `file_ids` | API migration then delete | Flow run API request + `intric-js` | `step_inputs[step_id].file_ids` | Update OpenAPI examples, JS client, idempotency, tests, and docs; preserve export lineage if needed. | Medium |
| Legacy form field type normalization | Backfill then delete | `flow_validators_form` and `FlowService` | Canonical `form_schema.fields[].type = text` | Backfill `string/email/textarea` to `text`, prove zero rows, remove normalizer/tests. | Medium |
| Unknown run payload passthrough | Keep | `flow_run_input_payload` and `FlowRunService` | Run payload validation boundary | Keep unless a stricter public schema is intentionally designed. | High |
| Frontend `getRedispatchFeedback` alias | Delete now | `flowRunRedispatchFeedback.ts` | `getRedispatchToastKind` | Remove alias and stale compatibility comment. | High |
| `FlowAIBuilderInput.focus` legacy string signature | Delete if TS confirms no string callers | `FlowAIBuilderInput.svelte` | Object-argument focus API | Current in-tree callers use object form; remove string branch after typecheck. | High |
| Mirrored instruction/input-template cleanup | Data migration then delete | `FlowEditor.ts`, `FlowStepEditPanel.svelte` | Backend data migration plus normal editor state | Backfill rows where input template mirrors instructions; remove auto-clear side effects. | Medium |
| Deprecated `flow_step_mcp_tools` source-reference guard | Keep | `test_ai_builder_importlinter_rules.py` | Import/architecture guard test | It protects the new MCP ownership invariant and is not dead compatibility. | High |

## Unreferenced Symbols And Exports

| Symbol / file | Evidence | Problem | Current owner | Proposed canonical home | Delete / merge path | Acceptance criteria | Tests required | Risk / trade-off | Human reviewability impact | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| `getRedispatchFeedback` | Declared as a backward-compatible alias at `frontend/apps/web/src/lib/features/flows/components/flowRunRedispatchFeedback.ts:7-8`; current component and test import `getRedispatchToastKind` at `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:16` and `frontend/apps/web/src/lib/features/flows/components/flowRunRedispatchFeedback.test.ts:2`. | The comment says existing tests/local imports use the alias, but local search found no importer. | `flowRunRedispatchFeedback.ts` | `getRedispatchToastKind` | Delete the alias and comment. | `rg -n "getRedispatchFeedback" frontend/apps/web/src` returns no hits. | Existing `flowRunRedispatchFeedback.test.ts` remains on canonical function. | Low; alias has no in-tree users. | Removes a false compatibility claim from a small utility. | High |
| `FlowAIBuilderInput.focus` string signature | Branch supports `options` as a string at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte:73-80`; current call sites pass object arguments at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte:64-69` and `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte:92`. | The component preserves an older imperative API shape after local callers moved to the object shape. | `FlowAIBuilderInput.svelte` | Object-argument focus API | Remove string overload and the legacy comment once TypeScript proves no string callers. | `rg -n "\\.focus\\(" frontend/apps/web/src/lib/features/flows/ai-builder` shows no string-argument caller. | Component test for focusing with placeholder/prefill, if one exists or is added. | Low; only exposed through component ref, so verify Svelte component consumers. | Shortens an imperative component API and removes a misleading legacy branch. | High |
| `normalize_legacy_config` | Function is defined at `backend/src/intric/flows/http_transport/normalizer.py:21-53`; production source search found only `is_authored_config`, not `normalize_legacy_config`, while tests import it at `backend/tests/unittests/flows/http_transport/test_normalizer.py:5`. | A legacy converter is test-only code unless persisted HTTP config rows still need it. | `http_transport.normalizer` | No owner if no legacy rows exist; authored config lives in `http_transport.authored_config`. | Run DB count for HTTP configs missing `auth`; if zero, delete `normalize_legacy_config` and its normalization tests, keeping `is_authored_config`. | `rg -n "normalize_legacy_config\\(" backend/src/intric` has no production call sites; DB query proves no legacy rows. | Keep tests for `is_authored_config`; delete tests that only exercise converter branches. | Medium; deletion is unsafe if old `flow_steps.input_config` / `output_config` rows lack the `auth` discriminator documented at `backend/src/intric/flows/http_transport/authored_config.py:65-70`. | Removes a broad `dict[str, Any]` converter from runtime-adjacent code. | Medium |

No other high-confidence unreferenced production files were found with local grep. `FlowFactory` is not a delete candidate: repositories depend on it at `backend/src/intric/flows/infrastructure/flow_repo.py:33-47`, `backend/src/intric/flows/infrastructure/flow_run_repo.py:26-42`, and `backend/src/intric/flows/infrastructure/flow_version_repo.py:10-17`, and the DI container provides it at `backend/src/intric/main/container/container.py:520`.

## Compatibility Shims And Duplicate Import Paths

| Concept | Existing locations | Problem | Current owner | Proposed canonical home | Merge / delete path | Acceptance criteria | Tests required | Risk / trade-off | Human reviewability impact | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| Flow package service/repository/domain shims | `backend/src/intric/flows/flow.py:1-37`, `backend/src/intric/flows/flow_repo.py:1-5`, `backend/src/intric/flows/flow_run_repo.py:1-5`, `backend/src/intric/flows/flow_service.py:1-5`, `backend/src/intric/flows/flow_version_repo.py:1-5` | The package exposes multiple import paths for the same domain/application/infrastructure concepts. | Shim files plus `_LAZY_EXPORTS` at `backend/src/intric/flows/__init__.py:22-40`. | Canonical owners named in `_LAZY_EXPORTS`: `domain.flow`, `application.flow_service`, `application.flow_run_service`, `infrastructure.*`. | First rewrite imports. Then delete shims and remove entries from `.importlinter` source modules at `backend/.importlinter:21-52` that name deleted modules. | `rg -n "intric\\.flows\\.(flow|flow_repo|flow_run_repo|flow_service|flow_run_service|flow_version_repo)(\\b| import)" backend frontend` has no non-canonical hits. | Replace `backend/tests/unit/test_server_startup_imports.py:74-95` with a smaller lazy-export test or delete if `_LAZY_EXPORTS` is removed. | Medium; `flow.py` still has production imports from AI Builder and `space_actor.py`, so it is staged, not immediate. | Reviewers see one import path per layer and stop chasing shim indirection. | High |
| `flow_run_service.py` logger-rebinding subclass | `backend/src/intric/flows/flow_run_service.py:5-21` imports the real service, exposes `logger`, subclasses `FlowRunService`, and mutates the application module logger before `create_run`. | This is not a plain shim; it changes behavior to support tests that import the wrong module. | `intric.flows.flow_run_service` | `intric.flows.application.flow_run_service` | Retarget imports in `backend/tests/unittests/flows/test_flow_run_service.py:27` and `backend/tests/unittests/flows/test_typed_io_run_service.py:17`; delete the subclass. | No code imports `intric.flows.flow_run_service`; tests patch canonical module if needed. | Flow run service unit tests still pass with canonical imports. | Low to medium; log-patching tests may need fixture changes. | Removes a racy module-level mutation that would alarm a reviewer. | High |
| `flow_dispatch.py` module alias | `backend/src/intric/flows/flow_dispatch.py:1-9` replaces its module with `intric.flows.application.flow_dispatch`; importers are `backend/tests/unittests/flows/test_flow_router.py:16` and startup re-export test at `backend/tests/unit/test_server_startup_imports.py:84`. | `sys.modules` aliasing hides the real owner and exists for compatibility import shape. | Shim module | `intric.flows.application.flow_dispatch` | Rewrite test import and delete alias module. | No import of `intric.flows.flow_dispatch`. | Router test imports application dispatch module directly. | Low; no production importers found. | Removes hidden module substitution from package import surface. | High |
| `flow_template_validation.py` cycle-break shim | `backend/src/intric/flows/flow_template_validation.py:1-17` re-exports file-domain DOCX validation and says it avoids import cycles; only current importer found is `backend/tests/unit/test_server_startup_imports.py:39`. | It is currently test-only, but the cycle concern may be real. Deleting it without a boundary guard risks reintroducing the old cycle. | Shim module | `intric.files.docx_template_validation` plus an import-linter boundary. | Add or update import-linter contract so flow validators do not import the files domain in a startup-cycling way; then delete this module if no importers remain. | Startup import test still covers server import; import-linter covers forbidden cycle. | Keep `backend/tests/unit/test_server_startup_imports.py:10-49` until import-linter is in place, then simplify. | Medium; need `git log` or ADR context to identify the original cycle. | Converts a vague compatibility module into an explicit boundary rule. | Medium |

## Duplicate Router Exports

| Concept | Evidence | Problem | Current owner | Proposed canonical home | Merge / delete path | Acceptance criteria | Tests required | Risk / trade-off | Human reviewability impact | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| `flow_consumer_router.py` endpoint re-exports | Router aggregator imports endpoint callables at `backend/src/intric/flows/api/flow_consumer_router.py:3-26` and exports them at `backend/src/intric/flows/api/flow_consumer_router.py:32-48`. | The module should assemble routers, not create another import surface for endpoint functions. | `flow_consumer_router.py` | Endpoint modules: `flow_upload_router.py`, `flow_run_execution_router.py`, `flow_run_evidence_router.py`, `flow_run_steps_router.py`. | Remove callable imports and `__all__` entries; keep only `router` assembly if this aggregator remains. | No tests or source import endpoint functions from the aggregator. | Replace `backend/tests/unit/test_server_startup_imports.py:113-213` identity assertions with a router-boundary/import-linter test. | Low; runtime route inclusion uses `router`, not callable re-exports. | Future endpoint edits happen in the endpoint module, not through an alias. | High |
| `flow_run_router.py` endpoint re-exports | Aggregator imports endpoint callables at `backend/src/intric/flows/api/flow_run_router.py:5-23` and exports them at `backend/src/intric/flows/api/flow_run_router.py:30-42`. | This duplicates the callable surface again below `flow_consumer_router.py`. | `flow_run_router.py` | Concrete run execution/evidence/steps routers. | Same as above; consider whether both aggregators are still worth keeping. | `flow_run_router.py` only exposes `router`, or is folded if one aggregation layer is enough. | Router inclusion smoke test and API route listing test. | Medium; two aggregators may encode consumer-vs-run grouping, so collapse only if API reviewer agrees. | Reduces endpoint ownership ambiguity for API maintainers. | High |

## Feature Flags / Branches That Never Fire

No findings.

Local search did not find flow-scoped feature flags or obviously unreachable `if False` / dead branch code. The main branch-like risks are compatibility branches that can still fire if persisted data or public request shapes contain legacy values; those are covered in the migration-gated sections below.

## Persisted-Shape Legacy Paths

| Legacy path | Evidence | Problem | Current owner | Proposed canonical home | Migration / deletion path | Acceptance criteria | Tests required | Risk / trade-off | Human reviewability impact | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| DOCX `template_file_id` compatibility | Publish resolves `template_file_id` and promotes missing assets at `backend/src/intric/flows/application/flow_service.py:880-919` and `backend/src/intric/flows/application/flow_service.py:931-964`; run-contract readiness has a legacy branch at `backend/src/intric/flows/flow_file_upload_service.py:382-395`; frontend selection falls back by `template_file_id` at `frontend/apps/web/src/lib/features/flows/templateFillConfig.ts:102-125`. | The code preserves old template selection shape after `flow_template_assets` became the canonical owner. | `FlowService`, `FlowFileUploadService`, frontend `templateFillConfig.ts`. | `flow_template_assets` table and `template_asset_id` in output config. | Backfill every `template_file_id`-only config to `template_asset_id`; prove zero rows remain; delete backend promotion, readiness fallback, frontend legacy match, and compatibility tests. | DB count for `output_config.template_file_id` without `template_asset_id` is zero; no frontend code searches assets by file ID for selection. | Migration test for backfill; API contract test for template asset ID; frontend component/helper test for asset ID only. | High if deleted without migration; old drafts/published versions could lose templates. | Converts template ownership from file ID heuristics to one asset identity. | Medium |
| Top-level run `file_ids` adapter | Canonical `step_inputs` shape exists at `backend/src/intric/flows/api/flow_models.py:410-434`, but `file_ids` remains a request field at `backend/src/intric/flows/api/flow_models.py:431-435`, is passed by router at `backend/src/intric/flows/api/flow_run_execution_router.py:171-184`, and adapted to step 1 at `backend/src/intric/flows/flow_run_step_inputs.py:104-128`. `intric-js` also includes `file_ids` in its run intent at `frontend/packages/intric-js/src/endpoints/flows.js:63-94`. | The legacy field competes with per-step file mapping and forces special step-1 behavior. | Run API schema, router, `FlowRunService`, `intric-js`. | `step_inputs[step_id].file_ids`. | Update OpenAPI examples and JS client to use only `step_inputs`; reject top-level `file_ids`; keep export lineage keys if they describe historical runs. | `FlowRunCreateRequest` has no top-level `file_ids`; `rg -n "file_ids\\?: string\\[\\]|file_ids=run_in.file_ids|apply_legacy_step_one_adapter" backend frontend` has no creation-path hits. | API contract tests for per-step file mapping; JS client idempotency test for sorted `step_inputs`; behavior test rejecting mixed legacy/canonical input can be deleted. | High; this is public API, not internal dead code. | Removes a special case that every future per-step-file reviewer would otherwise need to reason about. | Medium |
| Legacy form schema field types | `flow_run_input_payload.py:9-13` maps `string`, `email`, and `textarea` to `text`; `FlowService` normalizes create/update metadata at `backend/src/intric/flows/application/flow_service.py:91`, `backend/src/intric/flows/application/flow_service.py:182-184`, and `backend/src/intric/flows/application/flow_service.py:331`; unit tests preserve the behavior at `backend/tests/unittests/flows/test_flow_run_input_payload.py:124-134` and `backend/tests/unittests/flows/test_flow_validators.py:291-301`. | Pre-production should choose one field type vocabulary, but old persisted metadata may still carry the old vocabulary. | `flow_validators_form.py`, `flow_run_input_payload.py`, `FlowService`. | Canonical form schema field type set. | Backfill metadata JSON so every field type is canonical; then remove legacy normalization and tests. | DB query proves zero `form_schema.fields[].type in ('string','email','textarea')`. | Alembic migration test and API/service validation tests for canonical field types. | Medium; deletion without backfill changes run validation for existing drafts. | Makes form schema reviewable as one explicit type contract. | Medium |
| Legacy mirrored instruction/input-template cleanup | `FlowEditor` runs cleanup on init at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:281-324` and invokes it at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:817`; `FlowStepEditPanel` also clears matching instruction/input template state in a `$effect` at `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:767-780`. | Frontend state mutates itself to repair old AI Builder output, hiding data cleanup in UI effects. | `FlowEditor.ts` and `FlowStepEditPanel.svelte`. | Backend migration or canonical draft normalization before data reaches UI. | Backfill or reject rows where mirrored input templates represent old builder output; remove frontend auto-clear paths. | No frontend code contains `legacyTemplateCleanupStarted` or `autoClearedLegacyTemplateByStepId`; DB count for mirrored rows is zero or migration handles them. | Migration test for cleanup; frontend test proving normal edit path does not auto-clear current user input. | Medium; if old rows exist, deleting UI cleanup can re-expose duplicated prompt input. | Removes invisible editor mutations that make UI state harder to review. | Medium |
| Flow principal `user_id` compatibility | Flow runs now store `principal_type`, `principal_user_id`, and `principal_api_key_id` at `backend/src/intric/database/tables/flow_tables.py:327-344`; migration backfilled `principal_user_id` from `user_id` at `backend/alembic/versions/20260411_flow_run_identity_and_idempotency.py:42-63`; `FlowPrincipal.legacy_user_id` still writes `user_id` at `backend/src/intric/flows/principal.py:35-40` and `backend/src/intric/flows/principal.py:84-98`. | The old and new principal identities are kept in parallel, increasing query and authorization ambiguity. | `FlowPrincipal`, `FlowRuns`, `FlowRunRepository`. | `FlowPrincipal` plus non-null canonical principal columns. | Defer implementation ownership to the Phase 1 data-model reviewer, but delete old `user_id` write/read path once all flows use principal columns. | `flow_runs.user_id` is no longer required by runtime/repositories; migration removes column or marks it historical-only. | Data migration and repository integration tests for user and service-key principals. | High; principal identity is authorization-sensitive. | One identity model makes permission diffs safer to approve. | Medium |
| HTTP authored config legacy discriminator | Authored config says `auth` distinguishes it from legacy dict configs at `backend/src/intric/flows/http_transport/authored_config.py:65-70`; source uses `is_authored_config` to decide redaction/encryption behavior at `backend/src/intric/flows/api/flow_assembler.py:104-109` and `backend/src/intric/flows/application/flow_service.py:635-644`. | If persisted HTTP configs without `auth` exist, removing legacy support must be data-first. | `http_transport.authored_config` and `flow_service` config encryption paths. | `HttpAuthoredConfig` as the only stored shape. | Count and backfill legacy HTTP config rows; then delete `normalize_legacy_config` and any legacy tests. | Every HTTP step config has `auth`; no legacy converter remains. | Migration test and HTTP config validation tests. | Medium; current converter is unused, but persisted rows decide safety. | Clarifies HTTP config storage as one Pydantic contract. | Medium |

## Public Contract Compatibility

| Contract | Evidence | Recommendation |
|---|---|---|
| Unknown run payload passthrough | Test preserves an unknown `trace_id` at `backend/tests/unittests/flows/test_flow_run_service.py:736-765`; validation copies incoming payload before validating known form fields at `backend/src/intric/flows/flow_run_input_payload.py:33-52`. | Keep for now. Removing it would make the API stricter without a replacement contract and would hurt forward compatibility for external consumers. |
| `file_ids` export/lineage keys | Run creation should move to `step_inputs`, but export filters still know about `file_ids` at `backend/src/intric/flows/flow_run_export_json.py:558-568` and lineage includes runtime file IDs at `backend/src/intric/flows/flow_run_export_json.py:621-629`. | Do not blindly delete export fields while removing input request support; historical/audit output may need to preserve the old key. |
| Flow permission legacy alias | `Permission.FLOWS` remains an alias for newer flow permissions at `backend/src/intric/roles/permissions.py:28-59`, and tests accept it at `backend/tests/unittests/flows/test_flow_permissions.py:29-53`. | Defer implementation ownership to the Phase 1 API/auth or data-model reviewer. A smaller intermediate cleanup may be possible: remove `Permission.FLOWS` from implication tuples after proving no role/API-key rows still grant only `flows`, but do not delete the enum value until persisted permissions are migrated. |

## AI Builder Repair / Fallback Paths

Most AI Builder repair code is not dead code; it protects an active LLM boundary. The deletion issue is compatibility fields that remain after newer state/action owners were introduced.

| Path | Evidence | Verdict | Rationale |
|---|---|---|---|
| Orchestration `required_slot_names` compatibility input | `OrchestrationContext` says `has_new_evidence` and `required_slot_names` remain compatibility signals for tests/older callers at `backend/src/intric/flows/ai_builder/ai_builder_orchestrator.py:274-290`; planner still derives compatibility `required_slot_names` at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1174-1180`. | Migrate then delete if `action_policy` is authoritative everywhere. | This is a parallel action-eligibility path. It should not be preserved for tests once action policy is the canonical owner. |
| Legacy question ID from tool calls | `assistant_question_id` falls back from metadata to legacy tool calls at `backend/src/intric/flows/ai_builder/ai_builder_question_state.py:76-84` and parses `ask_structured_question` calls at `backend/src/intric/flows/ai_builder/ai_builder_question_state.py:134-158`; conversation model rejects rows without `message_id` at `backend/tests/unittests/flows/ai_builder/test_conversation_message_id.py:78-90`. | Backfill/verify then delete. | If all persisted conversation entries have metadata question IDs, the fallback is stale. If not, it is a migration guard. |
| Planner v1 provider fallback | Planner sets `drop_params=True` so unsupported JSON-mode providers still return parsable completions and says the v1 fallback path was otherwise lost at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1309-1315`. | Keep unless model/provider policy changes. | This is an explicit runtime compatibility choice at an external LLM seam, not dead code. |
| Proposal/parse repair loops | Proposal processor calls repair completion paths throughout `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1499-1589` and surfaces repair status events at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1723-1760`; orchestration pipeline owns repair retry accounting at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:173-228`. | Keep. | Repair loops handle active invalid LLM output and are reliability logic, not legacy code. |

## Migration Scaffolding Already Complete

| Item | Evidence | Verdict | Why |
|---|---|---|---|
| `flow_step_mcp_tools` table removal | Migration drops the obsolete table and states the new owner is assistant MCP tables at `backend/alembic/versions/20260426_drop_step_mcp_tools.py:1-10` and `backend/alembic/versions/20260426_drop_step_mcp_tools.py:24-30`; test ensures no source references the old table at `backend/tests/unittests/flows/ai_builder/test_ai_builder_importlinter_rules.py:309-321`. | Keep guard test. | This is a current invariant protecting single source of truth, not dead compatibility. |
| Builder envelope duplicate spec drop | Migration says `builder_plans.envelope_json` used to duplicate `spec_json` at `backend/alembic/versions/20260421_builder_plans_drop_envelope_spec.py:1-8`. | No deletion finding in this pass. | The migration documents an already-completed single-source cleanup; no live compatibility path was found in the scoped source review. |

## TODO / FIXME / XXX Inventory

| Marker | Evidence | Git blame age | Verdict | Rationale |
|---|---|---|---|---|
| `FIXME` string in import-linter failure text | `backend/tests/unittests/flows/ai_builder/test_importlinter_boundary.py:146-149` tells future developers to add a `FIXME` if an import-boundary violation is temporary. `git blame` shows `781c308e8` by CCimen on 2026-04-21 for lines 146-149. | 7 days as of 2026-04-28. | Keep. | This is test failure guidance, not an unresolved TODO. |

No actual flow-scoped `TODO`, `FIXME`, or `XXX` comments were found in source/tests by `rg -n "TODO|FIXME|XXX" ...`; the only hit is the test failure message above.

## Commented-Out Code Blocks

No findings.

Local grep for commented-out Python/TypeScript/Svelte code patterns found private field declarations in Svelte/TypeScript and explanatory comments, but no commented-out code block requiring deletion.

## Dead And Unnecessary Tests

| Test | Evidence | Problem | Delete / rewrite path | Replacement behavior coverage | Risk | Confidence |
|---|---|---|---|---|---|---|
| Shim re-export identity test | `backend/tests/unit/test_server_startup_imports.py:74-95` imports `intric.flows.flow`, `flow_service`, `flow_run_service`, `flow_repo`, `flow_run_repo`, `flow_version_repo`, and `flow_dispatch` and asserts names/modules match canonical owners. | It protects the compatibility paths we should remove. | Delete after imports are canonicalized; keep a small test that `intric.flows` package import has no heavy side effects at `backend/tests/unit/test_server_startup_imports.py:52-60`. | Pyright/import tests and direct canonical imports. | Low after shim migration. | High |
| Router callable re-export identity test | `backend/tests/unit/test_server_startup_imports.py:113-213` asserts handler name identity across router aggregators. | It preserves duplicate endpoint import surfaces instead of user-visible routing behavior. | Replace with route registration test and/or import-linter boundary; delete identity assertions. | API route list/contract tests for paths, operation IDs, and response models. | Low to medium; ensure route inclusion remains unchanged. | High |
| Template validation shim re-export test | `backend/tests/unit/test_server_startup_imports.py:37-49` imports `intric.flows.flow_template_validation` and checks it re-exports file-domain helpers. | Test protects a shim rather than the underlying cycle constraint. | Replace with import-linter rule or startup cycle smoke test; delete re-export identity check. | Server startup import test plus boundary rule. | Medium until original cycle is documented. | Medium |
| Legacy DOCX template asset compatibility tests | `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:61-136`, `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:140-223`, `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:227-269`, `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:273-285` preserve `template_file_id` fallback behavior. | Tests are correct today but become dead once asset-ID migration is complete. | Delete after DB backfill and source fallback deletion. | Migration test and canonical template asset publish/run-contract tests. | Medium; do not delete before data migration. | Medium |
| `normalize_legacy_config` tests | `backend/tests/unittests/flows/http_transport/test_normalizer.py:27-211` exercises legacy config conversion branches; production source does not call `normalize_legacy_config`. | Test-only behavior unless persisted rows need converter. | Delete converter tests after DB query/backfill; keep `is_authored_config` tests if the discriminator remains. | HTTP authored config validation/encryption tests. | Medium; depends on DB row count. | Medium |
| Flow permission legacy alias tests | `backend/tests/unittests/flows/test_flow_permissions.py:29-53` accepts `Permission.FLOWS` as alias for view/AI Builder/trace. | Not dead unless role data has migrated to granular permissions. | Keep until permission migration removes `Permission.FLOWS` from persisted roles/API keys. | Permission migration test and endpoint auth contract tests. | High if deleted too early. | High |

## Slop / Legacy Comment Inventory

| Location | Classification | Evidence | Verdict |
|---|---|---|---|
| `frontend/apps/web/src/lib/features/flows/components/flowRunRedispatchFeedback.ts:7` | Outdated compatibility comment | Says alias is used by existing tests/local imports; current imports use `getRedispatchToastKind`. | Delete with alias. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte:74` | Legacy compatibility comment | Documents old string signature; current call sites use object form. | Delete with string overload after typecheck. |
| `backend/src/intric/flows/flow_template_validation.py:1-5` | Intent comment | Explains module path stability and import-cycle concern. | Keep equivalent rationale as import-linter rule or ADR if shim is deleted. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1309-1315` | Intent comment | Explains `drop_params=True` preserves provider fallback behavior. | Keep unless provider policy changes. |
| `backend/src/intric/flows/application/flow_service.py:931-964` | Missing deletion owner | Method name says `legacy`, but there is no removal condition or migration pointer. | Add migration owner in PRD; then delete method after backfill. |

## Proposed Kill List

| Priority | Kill item | What to delete | Prerequisites | Validation commands / checks | Risk | Confidence |
|---:|---|---|---|---|---|---|
| 1 | Frontend redispatch alias | `getRedispatchFeedback` alias and stale comment at `flowRunRedispatchFeedback.ts:7-8`. | None beyond grep. | `rg -n "getRedispatchFeedback" frontend/apps/web/src`; `pnpm -C frontend/apps/web test:unit -- flowRunRedispatchFeedback --run` if supported. Phase 0 notes frontend unit tests may fail on missing `jsdom` at `docs/refactor/phase0/baseline.md:29`; treat that environment issue separately from this deletion. | Low | High |
| 2 | Router callable re-export surfaces | Callable imports and `__all__` entries in `flow_consumer_router.py:3-48` and `flow_run_router.py:5-42`; identity assertions in startup tests. | Add replacement route registration/import-boundary test. | Backend API route tests; import-linter if contract added. | Low/medium | High |
| 3 | Package shim imports | `flow_repo.py`, `flow_version_repo.py`, `flow_service.py`, `flow_run_repo.py`, `flow_dispatch.py`, later `flow.py`. | Rewrite imports; update `_LAZY_EXPORTS`; update `.importlinter`. | `rg` for shim paths; `cd backend && uv run pyright`; flow tests. | Medium | High |
| 4 | `flow_run_service.py` behavior shim | Delete subclass/logger rebinding. | Retarget tests to canonical service module. | `rg -n "intric\\.flows\\.flow_run_service"`; flow run service tests. | Low/medium | High |
| 5 | `normalize_legacy_config` | Converter function and conversion tests. | DB check/backfill for HTTP configs missing `auth`. | DB count query; HTTP transport tests. | Medium | Medium |
| 6 | Top-level run `file_ids` | Request field, router pass-through, step-one adapter, JS client field, compatibility tests. | Public API migration to `step_inputs`; update generated/client docs/examples. | API contract tests; frontend client tests; per-step file mapping tests. | High | Medium |
| 7 | Legacy DOCX `template_file_id` fallback | Backend promotion/readiness fallback, frontend legacy asset selection, compatibility tests. | DB backfill to `template_asset_id`; migration tests. | DB count query; template publish/run-contract tests; frontend template config tests. | High | Medium |
| 8 | Legacy form type normalization | `string/email/textarea` normalization and tests. | DB backfill; canonical schema validation policy. | DB count query; form schema API/service tests. | Medium | Medium |
| 9 | Mirrored input-template UI cleanup | `FlowEditor` init cleanup and `FlowStepEditPanel` `$effect`. | Backfill or prove zero affected rows. | DB count query; frontend editor tests. | Medium | Medium |

## Acceptance Criteria

- [ ] Every deleted import shim has zero production and test imports by `rg`, and `_LAZY_EXPORTS`, the `TYPE_CHECKING` mirror at `backend/src/intric/flows/__init__.py:42-50`, and `.importlinter` no longer name deleted modules.
- [ ] Router aggregation modules expose only `router` unless an endpoint callable re-export has a documented external consumer.
- [ ] `normalize_legacy_config` is either deleted after a DB proof of zero legacy HTTP rows, or explicitly kept with a migration owner and deletion condition.
- [ ] `template_file_id` compatibility is backed by a migration plan: count affected rows, backfill to `template_asset_id`, verify zero legacy rows, delete fallback code.
- [ ] Top-level run `file_ids` is removed only as an API contract migration with OpenAPI, `intric-js`, idempotency, examples, backend tests, and frontend tests updated together.
- [ ] Legacy form type normalization and mirrored input-template cleanup are removed only after data backfills or verified zero affected rows.
- [ ] Tests that only preserve compatibility identity are deleted or rewritten to behavior/import-boundary tests.
- [ ] No recommendation preserves old and new paths without a named deletion point.

## Tests Required

| Change | Test layer | Behavior protected |
|---|---|---|
| Shim deletion | Backend import/type gate | Canonical imports work and package import has no unwanted service/Celery side effects. |
| Router re-export deletion | API/router contract | All runtime/upload/evidence/step routes remain registered with expected operation IDs and response models. |
| `file_ids` API migration | API contract + `intric-js` tests | Consumers submit files through `step_inputs`; idempotency key derives from canonical payload; top-level `file_ids` is rejected with typed error. |
| Template asset migration | Alembic/integration/frontend helper tests | Legacy `template_file_id` rows become `template_asset_id` rows; publish/run-contract/frontend selection use asset ID only. |
| Form type migration | Alembic/service tests | Old field types are rewritten; validation accepts only canonical field types after migration. |
| Mirrored template cleanup deletion | Alembic/frontend component tests | Persisted mirrored rows are repaired once; editor no longer mutates normal user-authored input templates implicitly. |
| HTTP config cleanup | Alembic/unit tests | Stored HTTP configs have the `auth` discriminator; redaction/encryption validates `HttpAuthoredConfig` only. |

## Risk / Trade-Off

The main risk is deleting source-level compatibility before persisted data and public API consumers are migrated. This review therefore classifies items as immediate delete, import migration, API migration, or DB migration instead of producing one flat kill list. That costs more planning time, but it keeps future implementation diffs reviewable: each deletion PR can show the count query, migration, source deletion, and tests in one coherent chain.

Environmental limitation: I did not run DB count queries for persisted legacy row shapes in this pass. Those counts are required before implementation of migration-gated deletions.

## Human Reviewability Impact

The highest reviewability gain is removing aliases and identity tests that force reviewers to ask "which path is canonical?" The second gain is converting hidden frontend/backend cleanup paths into explicit migrations. A reviewer can approve `template_asset_id` cleanup when the diff shows: count query, backfill, fallback deletion, and tests. A reviewer cannot safely approve source-only deletion of code that might still be protecting rows.

## Final Scorecard

| Dimension | Score | Justification |
|---|---:|---|
| Maintainability | 5 | There is a clear path to remove compatibility, but today reviewers still need to inspect shims, `_LAZY_EXPORTS`, router re-exports, and legacy data paths. |
| Code Quality | 5 | Small stale aliases and behavior shims exist, and some broad legacy converters remain without visible production call sites. |
| Clean Architecture | 5 | Canonical application/domain/infrastructure owners exist, but compatibility modules and router callable re-exports blur boundaries. |
| Separation of Concerns | 5 | Router aggregators and frontend cleanup effects mix assembly/repair concerns with normal product behavior. |
| Single Source of Truth | 4 | `template_file_id` vs `template_asset_id`, top-level `file_ids` vs `step_inputs`, and old/new principal identity keep parallel concepts alive. |
| Human Readability | 6 | Many comments explain intent, but compatibility comments and legacy names still require historical reconstruction. |
| Human Reviewability | 5 | Deletion is possible, but several changes need DB/API migration evidence before a reviewer can approve them safely. |
| Runtime Reliability | 6 | Some compatibility paths protect old data, but the runtime would be more reliable once those paths become explicit migrations. |
| API Consumer DX | 5 | `step_inputs` is the better model, but top-level `file_ids` remains advertised in schema/client examples. |
| API Maintainer DX | 5 | Endpoint callable re-exports and schema compatibility fields make endpoint ownership harder to evolve. |
| Testability | 5 | Several tests protect compatibility identity rather than behavior; replacing them with route/import/migration tests would improve change safety. |

Overall score: 4/10, driven by Single Source of Truth.

## Confidence

High for shim/import/re-export findings, frontend alias deletion, TODO inventory, and commented-out-code inventory because they are grep-verifiable. Medium for persisted-shape deletion paths because row counts were not available in this documentation-only pass. Medium for API migration ordering because Agent E should confirm external consumer contract details before implementation.
