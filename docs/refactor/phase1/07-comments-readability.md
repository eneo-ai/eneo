# Phase 1 Agent G - Comments And Readability

TL;DR:
1. Human readability is below the project bar: the worst blockers are large lifecycle functions, broad "manager/processor" owners, and frontend state surfaces that require reconstruction from scattered comments.
2. Comment quality is mixed, not uniformly bad: `ai_builder_planner.py` and `flow_capability_manifest.py` contain load-bearing why-comments that should be preserved, while `ai_builder_materializer.py`, `FlowEditor.ts`, and several large tests use section banners and "Step 1/2/3" narration that should disappear behind named functions.
3. The strongest naming finding is not a generic variable: `FlowEditor.ts` hardcodes decision-support vocabulary (`beslutsunderlag`) into a general-purpose scaffold despite the repo invariant that AI Builder must not be specialty-scoped.
4. The biggest week-one comprehension failures are `AIBuilderPlanner.send_message`, `FlowRunExecutor.execute`, `resolve_step_input`, `AIBuilderProposalProcessor`, `FlowAIBuilderDriver`, `FlowEditor`, `FlowRunDialog`, and the large flow regression test files.
5. Recommended action is not mechanical splitting: preserve intent comments, delete restating comments and pre-production legacy cleanup, rename broad owners to lifecycle/domain names, and extract named phases only where the new name becomes the documentation.

## Review Basis

| Input | How it applies |
|---|---|
| `docs/engineering/comment-and-readability-standard.md:5` | Restating comments are defects because they add noise and become stale. |
| `docs/engineering/comment-and-readability-standard.md:17-25` | Forbidden comments include obvious control-flow narration, bad-name compensation, stale old-behavior comments, and commented-out code. |
| `docs/engineering/comment-and-readability-standard.md:27-35` | Prefer rename, extraction, value objects, branch naming, or moving code before adding a what-comment. |
| `docs/engineering/comment-and-readability-standard.md:37-50` | Names must reveal domain concept, lifecycle phase, canonical owner, and value nature. |
| `docs/engineering/maintainability-standards.md:7-11` | Every review starts from canonical ownership and week-one senior engineer comprehension. |
| `docs/engineering/maintainability-standards.md:69` | `manager`, `shared`, `types`, and similar names are avoid-by-default unless narrowly domain-specific. |
| `docs/engineering/maintainability-standards.md:71-85` | Delete-first refactoring applies to restating comments, fallback paths, and never-shipped compatibility. |
| `docs/refactor/phase1/README.md:20` | Agent G owns names, comments, long functions, AI slop, and week-one comprehension. |
| `docs/refactor/phase1/README.md:36-46` | This document must cite file:line evidence, current owner, canonical home, delete/merge path, tests, risk, reviewability, and confidence. |

Scope inspected:

| Area | Files |
|---|---:|
| Flow backend source, flow backend tests, flow frontend feature/routes, and `frontend/packages/intric-js/src/endpoints/flows.js` | 609 scoped source/test files |
| Files with non-trivial comments under the scoped classifier | 185 |
| Python functions over 60 LOC | 367 |
| TS/Svelte/JS class/function blocks over 60 LOC, best-effort brace scan | 13 |
| Files at or above 300 LOC | 174 |

Method caveat: comment classification is a reviewer aid, not a lint rule. The tally used Python `tokenize` for Python comments, a standalone-comment/JSDoc scan for JS/TS/Svelte files, and manual spot reclassification for the sampled high-volume files. JSDoc in `frontend/packages/intric-js/src/endpoints/flows.js` is counted as comment inventory because it is currently acting as a substitute for typed/generated API contracts; the recommended action there is not "groom JSDoc", it is to move the typing source of truth.

## Comment Classification Tally

No scoped `TODO`, `FIXME`, or `XXX` comments were found by the comment classifier. The high-risk comment issue is not unresolved TODOs; it is restating section structure and preserving legacy uncertainty.

| Rank | File | Intent | Restates | Outdated | TODO | Verdict |
|---:|---|---:|---:|---:|---:|---|
| 1 | `frontend/packages/intric-js/src/endpoints/flows.js` | 9 | 52 | 2 | 0 | JSDoc/type-cast noise; should be generated or centrally typed rather than hand-documented. |
| 2 | `backend/tests/unittests/flows/test_flow_capability_manifest.py` | 20 | 48 | 5 | 0 | Keep invariant comments; prune section/type-ignore noise while preserving behavior-contract explanations. |
| 3 | `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | 14 | 43 | 3 | 0 | Not a top offender by quality; preserve why-comments and reduce need for comments by splitting turn phases. |
| 4 | `backend/src/intric/flows/flow_capability_manifest.py` | 10 | 30 | 8 | 0 | Preserve parity/import-direction comments; do not treat all volume as bad. |
| 5 | `backend/src/intric/flows/ai_builder/ai_builder_materializer.py` | 3 | 34 | 3 | 0 | True offender: section banners and Step 1/2/3 narration should become named phase functions. |
| 6 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py` | 14 | 35 | 1 | 0 | Split by behavior/lifecycle and delete section narration. |
| 7 | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte` | 1 | 32 | 0 | 0 | Section comments expose too many responsibilities in one component. |
| 8 | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts` | 2 | 28 | 1 | 0 | Restating comments hide broad editor ownership and specialty-scoped defaults. |
| 9 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_materializer.py` | 2 | 27 | 0 | 0 | Replace section comments with behavior-oriented test classes/files. |
| 10 | `backend/tests/unittests/flows/ai_builder/test_pattern_registry.py` | 3 | 25 | 0 | 0 | Keep seed-invariant comments; delete section labels after test split. |
| 11 | `frontend/apps/web/src/lib/features/flows/components/FlowPromptEditor.svelte` | 2 | 20 | 1 | 0 | Comments describe synchronization mechanics that should be a named state owner. |
| 12 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_validator.py` | 3 | 15 | 4 | 0 | Split validator behavior groups; delete banner comments. |
| 13 | `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte` | 1 | 18 | 1 | 0 | Delete legacy cleanup path; extract state owners so banners vanish. |
| 14 | `backend/src/intric/flows/ai_builder/deterministic_signals_extractor.py` | 7 | 16 | 1 | 0 | Mostly acceptable parser rationale; prune incidental comments only. |
| 15 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompts.py` | 3 | 16 | 1 | 0 | Test grouping should be in class/file names, not banners. |
| 16 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py` | 1 | 17 | 0 | 0 | Large test file uses comments as navigation; split by service lifecycle. |
| 17 | `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py` | 3 | 14 | 1 | 0 | Section banners and marker-list comments hide concept names. |
| 18 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_conditional_prompt.py` | 2 | 14 | 1 | 0 | Preserve source-of-truth comments; prune restating test labels. |
| 19 | `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py` | 0 | 14 | 1 | 0 | Pure section-comment noise; split by route behavior. |
| 20 | `backend/tests/unittests/flows/ai_builder/test_discovery_mvs_gate.py` | 1 | 14 | 0 | 0 | Test classes should encode taxonomy/gate behavior. |

### Examples And Actions

| File:line | Classification | Problem | Proposed action |
|---|---|---|---|
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py:156-162` | `intent` | The schema-hash comment explains why the hash exists and how drift becomes diagnosable. | Keep. This is exactly the standard's allowed "why" comment. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py:217-250` | `intent` | Prepared-request fields carry non-obvious ordering and prompt/orchestrator consistency constraints. | Keep while extracting turn phases; do not delete as "too many comments." |
| `backend/src/intric/flows/flow_capability_manifest.py:121-126` | `intent` | Explains deliberate duplication from AI Builder capability code due import direction and parity testing. | Keep. Removing this would hide the canonical ownership trade-off. |
| `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:68-70` | `restates-code` | Section banner says "Pure Compiler" above `compile_changeset`; the function name should carry this. | Delete banner after naming module/function boundary `compile_ai_builder_changeset`. |
| `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:230-337` | `restates-code` | `# Step 1` through `# Step 5` narrate the body of a 173-LOC executor. | Extract `create_target_flow`, `create_missing_step_assistants`, `configure_existing_step_assistants`, `persist_compiled_steps`, `delete_removed_assistants`. |
| `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:499-528` | `restates-code` | Comments say "Start with existing metadata", "If spec has form_fields", and "Stamp description provenance." | Delete after extracting `merge_form_schema_metadata`, `apply_transcription_metadata_defaults`, `stamp_description_provenance`. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py:86-108` | `restates-code` | Comments narrate ref mapping, operation processing, and compiled-step construction. | Extract `build_edit_working_order`, `apply_ordered_edit_operations`, `compile_ordered_edit_steps`. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py:291` | `outdated/fallback` | "Fallback: append" silently chooses behavior for missing anchors. | Replace with explicit validation or `append_unanchored_step_edit` named branch plus test. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:35-48` | `restates-code` | Comments explain temp-ID stripping and reconciliation because that logic is embedded in a generic update closure. | Extract `prepareFlowUpdatePayload` and `reconcileActiveTemporaryStep`. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:344-388` | `restates-code` plus one valid invariant | "Debounced auto-save" and subscription comments are noise; "never auto-save when published" is the invariant. | Keep the published-flow invariant in `scheduleDraftAutosave`; delete surrounding narration. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:520-577` | `slop/specialty leak` | A general-purpose scaffold hardcodes Swedish decision-support copy and "Skriv beslutsunderlag." | Replace with neutral report/memo scaffold or delete the starter if it is not a canonical product concept. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:555` | `restates-code` | `// Step 3: Write decision brief...` narrates exactly what the following code does and reinforces specialty scope. | Delete with the scaffold rewrite. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:55-66` | `restates-code` | "Extracted state management" and "Extracted helpers" describe imports, not invariants. | Delete comments; import names should stand alone. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:763-780` | `outdated/delete` | Legacy cleanup preserves never-shipped old-builder behavior in a reactive effect. | Delete the effect and its comment if Agent D confirms no shipped migration need. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:34` | `restates-code` | Derivation banner is navigation for a large component. | Extract plan diff/advisory derivations into a small plan-view model module. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:94-105` | `intent` | Latch/user-intent comments explain non-obvious reactive lifetime. | Keep until the state is moved into a named view model. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:743-755` | mixed | The heading comment is useful accessibility/local DOM context; "scroll content area to top" restates code. | Keep the DOM-boundary comment; delete scroll narration. |
| `backend/tests/unittests/flows/test_flow_capability_manifest.py:182-195` | `intent` | Immutability and typed-pair comments express the behavior under test. | Keep, but remove incidental type-ignore comments elsewhere when possible. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py:438-440` | `restates-code` | Section banner substitutes for behavior-group organization in a 2,847-LOC test file. | Split by session lifecycle, send-message streaming, approval/revision/apply behavior. |
| `frontend/packages/intric-js/src/endpoints/flows.js:1-30` | `restates-code/type scaffolding` | JSDoc and casts compensate for handwritten client typing. | Move toward generated/central client types; avoid adding more JSDoc to stabilize API shapes. |

## Naming Audit

| Finding | Problem | Evidence | Current owner | Proposed canonical home | Rename/delete path | Acceptance criteria | Tests required | Risk/trade-off | Reviewability impact | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| Decision-support vocabulary leaks into a general-purpose starter. | `createTemplateFillStarter` hardcodes "Skriv beslutsunderlag" and decision-brief prompts; this makes one municipality workflow feel canonical. | General-purpose invariant forbids decision-support specialty terms at `CLAUDE.md:225-242` and repeats forbidden goldens at `CLAUDE.md:337-342`; offending scaffold lives at `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:520-577`. | `FlowEditor.ts` currently owns starter creation and assistant prompts. | A neutral flow starter definition owned by a product-specific scaffold module, or no starter if it is not a canonical product feature. | Rename `createTemplateFillStarter` to a neutral name such as `createThreeStepReportStarter`, replace specialty copy with neutral report/memo language, or delete the starter. | No user-visible AI Builder/Flow scaffold contains `beslutsunderlag`, `tjänsteskrivelse`, `ärendenummer`, `nämnd`, or `remiss` unless the user supplied that language. | Frontend unit/component test for starter copy and step names; AI Builder golden tests should assert domain-neutral default scenarios. | Copy change can affect screenshots/goldens and Swedish UX expectations; product owner should approve neutral text. | Reviewers can evaluate starter copy as one explicit artifact instead of scanning broad editor code. | High |
| `AIBuilderProposalProcessor` is a 2,663-LOC broad owner with a generic suffix. | "Processor" hides at least create-outline handling, edit validation/compilation, proposal repair, structured-question fallback, description repair, plan persistence, and SSE event emission. | Class starts at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:417`; `_process_edit_arguments` alone spans `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2054-2314`; file has no `#` comments (`rg '^\\s*#'` returned no hits), so names must carry the design. | `AIBuilderProposalProcessor`. | Split lifecycle owners: `AIBuilderPlanProposalRunner`, `AIBuilderEditProposalCompiler`, `AIBuilderProposalRepairLoop`, `AIBuilderStructuredQuestionResponder`. | Rename after extracting real phases; do not create pass-through wrappers. | Each extracted class/function has one public responsibility and uses domain lifecycle language. | Behavior tests for create proposal, edit proposal, repair retry, structured question fallback, and description repair through current public service/router paths. | Extraction is medium/high risk due streaming/SSE behavior and token telemetry. | Reviewers can approve one lifecycle phase at a time instead of re-reading a 2,663-LOC class. | High |
| `FlowsManager` uses a forbidden generic suffix for a narrow list-store. | The module manages a flow list, not all flow behavior. `manager` obscures that its state is list-scoped and space-scoped. | `FlowsManager` context and functions at `frontend/apps/web/src/lib/features/flows/FlowsManager.ts:11-68`; imports in `FlowActions.svelte`, `CreateFlowDialog.svelte`, and route page at `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/+page.svelte:6-33`. | `FlowsManager.ts`. | `FlowListStore` or `SpaceFlowListStore`. | Rename file/context/functions in one frontend-only PR; no behavior change. | Public component call sites read `getFlowListStore()` / `initSpaceFlowListStore()` and state fields remain `flows`/`spaceId`. | Frontend unit tests if present; otherwise `pnpm -C frontend check` once repo-wide baseline allows. | Low; route/component import churn only. | Diff becomes a mechanical rename with obvious intent and small blast radius. | High |
| `FlowEditor` is a broad feature service whose name hides autosave, assistant lifecycle, step ordering, validation, starter scaffolds, and legacy cleanup. | Week-one readers cannot infer which concept owns assistant save state, template starter creation, typed-IO validation, and step remapping. | `initFlowEditor` spans `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:27-820`; comments at `FlowEditor.ts:334-388`, `FlowEditor.ts:398-518`, and `FlowEditor.ts:520-577` mark separate lifecycles. | `FlowEditor.ts`. | Keep `FlowEditor` as facade only if it delegates to named owners: `FlowDraftAutosave`, `FlowStepDraftMutations`, `FlowAssistantDraftSync`, `FlowStarterScaffold`. | Extract one lifecycle at a time; delete comments that become function names. | `initFlowEditor` falls below 250 LOC or becomes a thin composition root; new owners have behavior tests. | Component/service tests for autosave gating, temp step reconciliation, insertion/remap, and starter creation. | Medium because autosave and assistant creation are user-visible. | Future reviewers see isolated behavior changes rather than a large editor diff. | High |
| `FlowRunDialog` stores many primitive maps keyed by step id. | State names are concrete, but ownership is unclear because upload, recording, wizard, template readiness, form payload, and run submission all live in one component. | State fields at `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:71-89`; `triggerRun` builds payload at `FlowRunDialog.svelte:794-858`; file is 1,196 LOC. | `FlowRunDialog.svelte`. | `FlowRunWizardState`, `FlowRuntimeUploadState`, and `FlowRunIntentBuilder` under the existing flow feature area. | Extract without adding a card/component layer; keep user flow unchanged. | Dialog script separates upload/recording state from run-intent payload construction. | Component tests for required fields, upload mapping, audio recording retry, and run payload. | Medium due complex UI state. | Reviewers can test state modules without parsing markup. | Medium |
| Handwritten client `initFlows` hides a public API client surface behind JSDoc/casts. | JSDoc volume and casts compensate for weak generated typing; future API changes can drift silently. | `frontend/packages/intric-js/src/endpoints/flows.js:1-30`, `frontend/packages/intric-js/src/endpoints/flows.js:386`, and `frontend/packages/intric-js/src/endpoints/flows.js:413-450` show handwritten request shaping and casts. | `frontend/packages/intric-js/src/endpoints/flows.js`. | Generated OpenAPI client or a narrowly named handwritten adapter such as `createFlowApiClient`. | Do not add more JSDoc; converge on generated types or a typed adapter boundary. | Flow endpoint request/response types come from one source. | Client contract tests for create run, upload, evidence, artifact signed URL. | Medium; API client change can touch many frontend routes. | API diffs become schema/client-generation diffs instead of hand-edited JS. | Medium |

## Slop Comment And Code Inventory

| Pattern | Evidence | Verdict | Proposed action |
|---|---|---|---|
| Comments narrate ordered phases instead of naming phases. | `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:230-337`. | Maintainability defect. | Extract named phase functions and delete comments. |
| Section banners compensate for oversized files/components. | `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:55-66`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:34`, `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py:241-243`. | Maintainability defect. | Split by lifecycle/component responsibility, not by banner headings. |
| Legacy cleanup with no shipped-user deletion point. | `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:763-780`. | Delete candidate. | Agent D should confirm no active migration; then delete effect and test any current valid input-template behavior. |
| Generic suffixes hide ownership. | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:417`, `frontend/apps/web/src/lib/features/flows/FlowsManager.ts:11-68`. | Naming defect. | Rename/extract to lifecycle/domain owners. |
| Specialty vocabulary leaks into general-purpose UI defaults. | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:520-577`; invariant at `CLAUDE.md:225-242`. | High-priority readability/product-language defect. | Replace with domain-neutral scaffold or delete starter. |
| Type-ignore comments become visual noise. | `backend/tests/unittests/flows/test_flow_capability_manifest.py:95-96`, `backend/tests/unittests/flows/test_flow_capability_manifest.py:187-190`. | Secondary cleanup. | Keep behavior tests; isolate mutation attempts through small helper if type ignores remain necessary. |
| Handwritten JS client uses comments/casts as type system. | `frontend/packages/intric-js/src/endpoints/flows.js:1-30`. | Boundary typing defect. | Generated/central types rather than more comments. |

## Function Length Distribution

| Bucket | Count | Interpretation |
|---|---:|---|
| Python functions 61-90 LOC | 237 | Mostly tests and medium helpers; refactor opportunistically when touching files. |
| Python functions 91-120 LOC | 69 | Needs lifecycle grouping before more feature work in the same area. |
| Python functions 121-200 LOC | 47 | Refactor candidates; require explicit phase names and behavior tests. |
| Python functions 201+ LOC | 14 | Blocking readability hotspots. |
| TS/Svelte/JS blocks over 60 LOC | 13 | Mostly broad classes/stores/components; split by state owner or generated client boundary. |

Top functions and proposed split names:

| Function/block | LOC | Proposed split / canonical owner |
|---|---:|---|
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py:944-1536` `send_message` | 593 | `claim_builder_turn`, `append_user_turn`, `prepare_planner_turn`, `dispatch_server_owned_builder_action`, `invoke_planner_pipeline`, `persist_builder_turn_events`, `release_builder_turn_claim`. |
| `backend/src/intric/flows/runtime/executor.py:316-731` `execute` | 416 | `claim_run_for_execution`, `load_published_runtime_definition`, `bootstrap_run_execution_state`, `claim_next_step`, `execute_claimed_step`, `persist_step_success_or_failure`, `finalize_run_outcome`. |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery.py:119-473` `analyze_discovery` | 355 | `collect_discovery_signals`, `classify_missing_mvs_slots`, `select_discovery_followup`, `build_discovery_analysis`. |
| `backend/src/intric/flows/runtime/step_input_resolution.py:54-388` `resolve_step_input` | 335 | `validate_step_input_source`, `resolve_base_input_source`, `load_runtime_files_for_step`, `render_question_binding`, `validate_contract_candidate`, `build_step_input_value`. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py:488-773` `_prepare_planner_request` | 286 | `resolve_requirements_state`, `build_prompt_context`, `build_action_policy`, `assemble_planner_messages`, `compute_turn_prompt_hash`. |
| `backend/src/intric/flows/runtime/step_execution_runtime.py:738-1013` `complete_step_execution` | 276 | `build_step_output_payload`, `persist_step_result`, `record_step_attempt_success`, `collect_step_evidence`, `emit_step_completion_audit`. |
| `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2054-2314` `_process_edit_arguments` | 261 | `parse_edit_tool_payload`, `canonicalize_edit_resources`, `validate_edit_draft_for_flow`, `compile_edit_preview`, `persist_edit_plan`. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:96-992` `FlowAIBuilderDriver` | 897 | Keep driver facade; extract `AIBuilderStreamReader`, `AIBuilderProtocolMapper`, `AIBuilderSessionCommands`, `AIBuilderPlanCommands`. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:27-820` `initFlowEditor` | 794 | `FlowDraftAutosave`, `FlowStepDraftMutations`, `FlowAssistantDraftSync`, `FlowStarterScaffold`, with `FlowEditor` as composition root only. |
| `frontend/packages/intric-js/src/endpoints/flows.js:6-578` `initFlows` | 573 | Replace handwritten client surface with generated flow API client or typed `createFlowApiClient` grouped by authoring/runtime/evidence/upload. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:26-282` `FlowAIBuilderService` | 257 | Extract session state, transport lifecycle, available-resource loading, plan action commands. |
| `frontend/apps/web/src/lib/features/flows/components/FlowTemplateState.svelte.ts:30-283` `FlowTemplateState` | 254 | Split template asset list state, inspection state, and persistence commands. |
| `frontend/apps/web/src/lib/features/flows/flowAssistantSaveManager.ts:19-218` `AssistantSaveManager` | 200 | Rename to `AssistantDraftSaveQueue`; expose enqueue/flush/status and hide cache/retry details. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:794-858` `triggerRun` | 65 | Extract `buildFlowRunIntentPayload` and `submitFlowRunIntent`. |

Full inventory note: the 61-120 LOC group is too large to turn into a useful hand-maintained table in Phase 1. The PRD should regenerate it with the AST command from this review, then require every touched >60 LOC function to either get a phase split or a written "keep as is" justification. This is a deliberate reviewability trade-off: the high-risk phase owners above are actionable; a 380-row appendix would bury the signal.

## Readability Anti-Patterns

| Anti-pattern | Evidence | Why it matters | Proposed canonical fix |
|---|---|---|---|
| God-method lifecycle orchestration | `AIBuilderPlanner.send_message` at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:944-1536`; `FlowRunExecutor.execute` at `backend/src/intric/flows/runtime/executor.py:316-731`. | Reviewers must reason about locking, state mutation, streaming, validation, retries, and persistence in one body. | Lifecycle phase methods with explicit input/output dataclasses only where the dataclass clarifies state. |
| Broad primitive bags | `question_answer: dict[str, Any]` in `backend/src/intric/flows/ai_builder/ai_builder_planner.py:950`; `context: dict[str, Any]` and `version_metadata: dict[str, Any]` in `backend/src/intric/flows/runtime/step_input_resolution.py:57-63`; `lastInputPayload: Record<string, unknown>` in `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:67`. | Names cannot explain contract shape because there is no typed contract. | Typed request/value objects at boundaries; frontend generated or central types. |
| Broad catch blocks inside long functions | Runtime executor catches attempts, step failures, webhook failures, and audit failures at `backend/src/intric/flows/runtime/executor.py:545`, `backend/src/intric/flows/runtime/executor.py:624`, `backend/src/intric/flows/runtime/executor.py:693`, and `backend/src/intric/flows/runtime/executor.py:1102`. | Error intent is buried in the long function and hard to audit. | Named error-boundary functions with domain-specific exception handling and behavior tests. |
| Comments compensate for unclear ownership | `FlowEditor.ts:35-48`, `FlowEditor.ts:334-388`, `FlowEditor.ts:398-518`. | Comments tell the reader "what this block is" because `FlowEditor` owns too much. | Extract named owners and delete the comments. |
| Handwritten API typing | `frontend/packages/intric-js/src/endpoints/flows.js:1-30`. | JSDoc/casts can drift from FastAPI/OpenAPI contracts. | Generated or central flow API types. |
| Pre-production compatibility preserved in UI state | `FlowStepEditPanel.svelte:763-780`. | Future readers must understand old behavior that should not exist in a pre-production product. | Delete with regression coverage for current intended behavior. |

## Week-One Senior Engineer Stuck Points

| Rank | File | Why a new senior engineer gets stuck | Proposed fix |
|---:|---|---|---|
| 1 | `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | `send_message` mixes budget defaults, session locking, metadata resolution, prompt preparation, server-owned actions, LLM invocation, repair, persistence, and streaming in one 593-LOC method. | Extract turn lifecycle phases and keep why-comments on prompt/orchestrator consistency. |
| 2 | `backend/src/intric/flows/runtime/executor.py` | `execute` owns run claim, definition loading, step loop, attempt creation, typed/generic failure, webhook delivery, terminalization, and audit swallowing. | Split execution phases; make transaction/error boundaries explicit. |
| 3 | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py` | A 2,663-LOC "Processor" class hides multiple proposal lifecycles and has no inline phase comments; the name carries no domain boundary. | Extract lifecycle owners and rename to proposal/edit/repair-specific names. |
| 4 | `backend/src/intric/flows/runtime/step_input_resolution.py` | `resolve_step_input` is a 335-LOC function where runtime files, binding interpolation, legacy mirrored prompts, typed IO validation, and diagnostics interact. | Split into source resolution, runtime file loading, binding rendering, and contract validation. |
| 5 | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts` | One initializer owns editor state, autosave, assistant persistence, step mutations, starter scaffolds, template cleanup, and validation. | Keep facade; extract state/action modules. |
| 6 | `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte` | Many keyed primitive state maps and a 1,196-LOC component make upload/run wizard ownership hard to identify. | Extract wizard state, upload state, and run intent builder. |
| 7 | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts` | 897-LOC class spans transport, parsing, protocol mapping, and command dispatch. | Split stream reader, protocol mapper, and command modules. |
| 8 | `frontend/packages/intric-js/src/endpoints/flows.js` | Handwritten JSDoc/casts require understanding generated-vs-manual client conventions before changing an endpoint. | Move to generated/central typed client boundary. |
| 9 | `backend/tests/unittests/flows/test_flow_router.py` | 3,589-LOC router test file mixes authoring, runtime, evidence, artifact, permission, and aliases. | Split by public API journey and behavior. |
| 10 | `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py` | 3,270-LOC integration file mixes create/edit/apply regressions, repair loops, and API streaming details. | Split by AI Builder session journey and use shared factories. |

## Work Items

| Priority | Work item | Files affected | Acceptance criteria | Tests required | Risk/trade-off | Reviewability impact | Confidence |
|---:|---|---|---|---|---|---|---|
| P1 | Remove specialty-scoped starter language. | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts`; related frontend tests/goldens. | No general-purpose starter or golden contains forbidden decision-support terms unless user-provided. | Frontend behavior test for scaffold creation; golden/copy assertions where applicable. | Product copy change. | Small, visible copy diff with clear invariant. | High |
| P1 | Delete pre-production legacy cleanup effect if no active migration owner exists. | `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte`, likely `FlowStepAssistantState.svelte.ts` if state becomes unused. | The effect and `autoClearedLegacyTemplateByStepId` state are gone or documented with real migration owner/deletion point. | Component/unit test for intended input-template override behavior. | Could reintroduce stale mirrored template only if current bug still exists. | Removes hidden side effect and legacy uncertainty. | Medium |
| P1 | Split `AIBuilderPlanner.send_message` by turn lifecycle. | `backend/src/intric/flows/ai_builder/ai_builder_planner.py` and focused tests. | `send_message` becomes a readable orchestration outline under 150 LOC; prompt/orchestrator invariants stay documented. | Existing planner send-message tests plus one integration test for lock release and streaming terminal event. | High due streaming and lock behavior. | Reviewers can approve lifecycle steps independently. | High |
| P1 | Split runtime `execute` by run lifecycle and error boundaries. | `backend/src/intric/flows/runtime/executor.py`. | `execute` calls named phases; broad catches are isolated and classified. | Runtime tests for duplicate start, typed IO failure, generic failure, webhook failure, cancelled run, audit failure. | High due runtime reliability. | Failure-mode diffs become auditable. | High |
| P2 | Rename/extract `AIBuilderProposalProcessor` responsibilities. | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`, planner imports, tests. | No class named only `Processor` owns multiple proposal lifecycles; create/edit/repair paths have named owners. | Proposal processor test split by create, edit, repair, structured question, description repair. | Medium/high due large test blast radius. | Smaller diffs and clearer ownership. | High |
| P2 | Rename `FlowsManager` to a list-store name. | `frontend/apps/web/src/lib/features/flows/FlowsManager.ts`, `FlowActions.svelte`, `CreateFlowDialog.svelte`, route page. | Context and file names say `FlowListStore` or `SpaceFlowListStore`; no behavior change. | Typecheck and existing route/component tests. | Low. | Mechanical rename is easy to review. | High |
| P2 | Replace comments-as-navigation in large frontend components with extracted state/view models. | `FlowStepEditPanel.svelte`, `FlowAIBuilderPlanPane.svelte`, `FlowRunDialog.svelte`. | Section banners are deleted because the extracted modules carry names. | Component tests for affected interactions. | Medium due UI state. | Reviewers can approve one UI state owner at a time. | Medium |
| P3 | Prune test section banners during behavior-test splits. | Large files under `backend/tests/unittests/flows/**` and `backend/tests/integration/flows/**`. | Test file names/classes describe behavior; comments explain only non-obvious invariants. | Existing test commands; no assertion weakening. | Low/medium; test movement can create noisy diffs. | Test reviews become journey-based. | Medium |

## Delete Or Preserve

| Item | Verdict | Evidence | Reason |
|---|---|---|---|
| Planner/schema/action-policy why-comments | Preserve | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:156-167`, `backend/src/intric/flows/ai_builder/ai_builder_planner.py:217-250`, `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1151-1158`. | They explain drift, ordering, and prompt/orchestrator invariants. |
| Flow capability manifest parity comments | Preserve | `backend/src/intric/flows/flow_capability_manifest.py:121-126`, `backend/src/intric/flows/flow_capability_manifest.py:844-854`. | They document deliberate duplication and behavior difference from legacy validator. |
| `ai_builder_materializer.py` section and Step comments | Delete after extraction | `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:68-70`, `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:230-337`, `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:499-528`. | They restate code and reveal missing phase names. |
| Flow editor scaffold specialty terms | Delete/replace | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:520-577`. | Violates general-purpose invariant. |
| Flow step legacy cleanup effect/comment | Delete if no migration owner | `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:763-780`. | Pre-production compatibility without deletion point. |
| Test invariant comments that explain behavior under test | Preserve selectively | `backend/tests/unittests/flows/test_flow_capability_manifest.py:182-195`. | These explain behavior contracts, not implementation mechanics. |

## Acceptance Criteria

- Every retained comment in scoped flow code answers "why, invariant, ordering, migration, security, idempotency, or incident"; comments that only label sections or narrate code are deleted.
- No general-purpose AI Builder or Flow scaffold contains the forbidden specialty terms listed in `CLAUDE.md:337-342` unless the user supplied them.
- `AIBuilderPlanner.send_message`, `FlowRunExecutor.execute`, `resolve_step_input`, and `_process_edit_arguments` have named lifecycle phases with behavior tests before additional feature work lands in those areas; each extracted phase is testable through behavior or a real seam without mocking same-module implementation details.
- `manager` / `processor` names remain only where the file/class has a narrow domain-specific responsibility and one reason to change.
- Frontend flow state modules name their ownership: list store, editor facade, autosave, assistant draft sync, run wizard, upload state, and run intent builder.
- Large test files are split by user-visible behavior or lifecycle, not by arbitrary line count.
- Phase 2 synthesis treats comment cleanup as delete/rename/extract work, not as a request to add more prose.

## Validation Commands

These are documentation recommendations; source tests were not run during this Agent G pass. Suggested validation once implementation work begins:

```bash
cd backend && uv run pyright
cd backend && ./.venv/bin/python -m pytest tests/unittests/flows/ai_builder tests/unittests/flows/test_flow_executor_runtime.py tests/unittests/flows/test_flow_router.py
pnpm -C frontend/apps/web test:unit -- --run
pnpm -C frontend check
```

Known baseline caveat from `docs/refactor/phase1/README.md:54-59`: backend Pyright currently passes, flow-scoped Ruff has import-order failures, and frontend check/unit tests have repo-wide/environment failures.

## Claude Peer Loop

Iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, and `MIN_SCORE: 6`. Accepted corrections:

| Claude challenge | Codex resolution |
|---|---|
| Distinguish file LOC from class/function LOC and fix the mistaken `initFlows` evidence. | Corrected frontend measurements: `FlowEditor.ts` is 825 LOC and `initFlowEditor` spans `FlowEditor.ts:27-820`; `FlowAIBuilderDriver` class spans `FlowAIBuilderDriver.ts:96-992`; `FlowAIBuilderService` spans `FlowAIBuilderService.svelte.ts:26-282`; `initFlows` is the JS client at `frontend/packages/intric-js/src/endpoints/flows.js:6-578`. |
| Do not classify `flow_capability_manifest.py` and `ai_builder_planner.py` as simple comment offenders. | Reclassified them as high-volume files with important why-comments and only selective restating noise. |
| Add the specialty-vocabulary leak in `FlowEditor.ts`. | Added as the top naming/readability finding with `CLAUDE.md` invariant citations. |
| Treat `FlowStepEditPanel.svelte` legacy cleanup as deletion, not comment rewrite. | Added P1 deletion work item and delete/preserve row. |
| Add week-one stuck-point list and sharper canonical homes. | Added the ten-file stuck-point table and ownership-oriented work items. |

Iteration 2 verification is recorded below after this document was revised.

Iteration 2 returned `VERDICT: green`, `GREEN_LIGHT: yes`, and `MIN_SCORE: 7`. Accepted non-blocking follow-ups:

| Claude verification follow-up | Codex resolution |
|---|---|
| Make tally methodology reproducible enough for Phase 2. | Added a method caveat explaining Python tokenization, standalone JS/TS/Svelte/JSDoc scanning, and manual spot reclassification. |
| Cross-link the specialty-language issue to AI Builder and test reviewers. | Added a cross-review dependency below so Agent A and Agent H can scrub prompts/goldens instead of leaving this as frontend-only copy cleanup. |
| Strengthen phase-split acceptance beyond an LOC gate. | Updated acceptance criteria to require behavior-testable phases and to avoid same-module implementation-detail mocking. |

## Cross-Review Dependencies

| Dependency | Owner | Why Agent G needs it |
|---|---|---|
| Specialty-language scrub across AI Builder prompts, pattern registry, and goldens. | Agent A (`01-ai-builder.md`) and Agent H (`08-tests.md`). | `FlowEditor.ts:520-577` proves the frontend starter leaks decision-support language, but AI Builder prompt packs and golden fixtures may have the same issue; Phase 2 should bundle these into one domain-neutrality PRD. |
| Legacy cleanup deletion decision for `FlowStepEditPanel.svelte:763-780`. | Agent D (`04-dead-and-legacy.md`). | Agent G recommends deletion if there is no active migration owner; Agent D should confirm whether any current saved drafts still need this compatibility path. |
| API client typing source of truth for `frontend/packages/intric-js/src/endpoints/flows.js`. | Agent E (`05-api-consumer.md`) and Agent I (`09-api-maintainer.md`). | The comment/JSDoc smell is a symptom of handwritten API typing; the canonical fix belongs with API consumer/maintainer contract work. |

## Scorecard

| Dimension | Score | Justification |
|---|---:|---|
| Maintainability | 5 | The biggest concepts have visible owners today, but several are too broad for safe week-one comprehension. |
| Code Quality | 5 | Many comments are good, but restating comments, broad names, and primitive bags are common in hotspots. |
| Clean Architecture | 6 | Most findings are readability/ownership issues rather than direct dependency inversions, but router/runtime/frontend boundaries still suffer from broad orchestration functions. |
| Separation of Concerns | 4 | `send_message`, `execute`, `FlowEditor`, `FlowRunDialog`, and `AIBuilderProposalProcessor` each combine multiple lifecycle phases. |
| Single Source of Truth | 5 | Commented parity and duplicated client/API contracts need explicit owners; specialty scaffold copy is not centralized. |
| Human Readability | 4 | A new senior engineer would struggle in the largest flow/AI Builder files without reconstructing lifecycle phases manually. |
| Human Reviewability | 4 | Diffs in the largest files are hard to approve because comments, names, and tests do not isolate behavior changes. |
| Overall | 4 | Refactor required in the worst hotspots before further feature work in those same areas. |
