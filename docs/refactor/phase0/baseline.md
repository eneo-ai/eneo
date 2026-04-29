# Phase 0 Baseline

TL;DR:
1. The flow review surface is large: the focused backend/frontend/test scope is 187,280 LOC across 1,361 files.
2. Backend test collection works locally with `./.venv/bin/python -m pytest --collect-only`: 6,166 selected tests collected, 41 deselected.
3. `uv run pyright` is green, while direct `pyright` is misleading because it cannot resolve backend dependencies in this shell.
4. Flow-scoped Ruff is not green: 18 import-order issues under `src/intric/flows` and flow tests.
5. Claude iteration 1 forced Phase 0 to add cross-cutting invariants before launching reviewers: closed statuses, published definition JSON, Celery/beat, audit swallowing, shim imports, and flow-scoped frontend diagnostics.

## Command Baseline

| Command | Result | Notes |
|---|---:|---|
| `docker ps --format '{{.Names}}' \| sort` | Pass | Containers visible: `eneo-41ae93-celery-worker-flows-1`, `eneo-41ae93-db-1`, `eneo-41ae93-eneo-1`, `eneo-41ae93-redis-1`. |
| `docker exec eneo-41ae93-eneo-1 pwd` | Blocked | Tool rejected: `approval required by policy, but AskForApproval is set to Never`. Same policy blocked requested DB `psql` access via `docker exec`. |
| `backend/.venv/bin/python --version` | Pass | Python 3.11.14. |
| `backend/.venv/bin/python -m pytest --version` | Pass | pytest 7.4.4. |
| `ruff --version` | Pass | ruff 0.14.4. |
| `pyright --version` | Pass | pyright 1.1.408. |
| `pnpm --version` | Pass | pnpm 10.33.0. |
| `./.venv/bin/python -m pytest --collect-only` from `backend/` | Pass | `6166/6207 tests collected (41 deselected) in 19.94s`. |
| `pyright` from `backend/` | Fail/noisy | 32,086+ errors because direct pyright cannot resolve imports such as `pydantic`, `fastapi`, and `sqlalchemy`; use `uv run pyright`. |
| `uv run pyright` from `backend/` | Pass | `0 errors, 0 warnings, 0 informations`. |
| `ruff check --no-fix backend` from repo root | Fail | 203 import-order issues across backend, mostly migrations/tests. |
| `uv run ruff check --no-fix src/intric/flows tests/unittests/flows tests/integration/flows` | Fail | 18 flow-scoped import-order issues. |
| `pnpm -C frontend check` | Fail | `@eneo/ui`: 18 errors; `@intric/ui`: 6 errors, 1 warning; `@intric/web`: 36 errors, 7 warnings. |
| `pnpm -C frontend check 2>&1 \| rg ...flow...` | Fail | Complete unique flow-scoped file:line diagnostics found by the filtered command: `frontend/packages/intric-js/src/endpoints/flows.js:440`, `FlowAIBuilderHarness.svelte:15`, `FlowAIBuilderEditHost.svelte:18`, `FlowsTable.svelte:88`, `FlowsTable.svelte:133`, and `ai-builder/+page.svelte:16`. |
| `pnpm -C frontend test -- --run` | Fail | The root frontend package has no usable `test` script through this invocation; pnpm returned `ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL`. |
| `pnpm -C frontend/apps/web test:unit -- --run` | Fail | Vitest executed 63 test files: 57 files and 460 tests passed, but the run failed with 6 unhandled `ERR_MODULE_NOT_FOUND` errors for missing `jsdom`. |

## Git State

| Signal | Value |
|---|---|
| Repository root | `/Users/ccimen/eneo/eneo` |
| Current branch | `feature/flows-hardening-tal-till-text` |
| HEAD | `91e981de Clarify flow knowledge evidence counts` |
| Dirty worktree | Yes |

Pre-existing modified/untracked files include `scripts/run_codex_review.sh`, `AGENTS.md`, `PRODUCT.md`, `backend/celerybeat-schedule`, `docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md`, `docs/engineering/`, and `prompt.md`. This review only writes under `docs/refactor/`.

## Focused Scope Size

| Scope | Measurement |
|---|---:|
| Focused files in `backend/src/intric/flows`, flow tests, and flow frontend feature/routes | 1,361 files |
| Focused LOC (`*.py`, `*.ts`, `*.svelte`) | 187,280 |
| Backend high-risk text hits (`Any`, `dict[str, Any]`, broad catches, legacy/fallback/repair/shim terms) | 2,623 lines |
| Backend source-only high-risk text hits under `backend/src/intric/flows` | 2,102 lines |
| Frontend high-risk text hits (`any`, `unknown`, `Record<string, unknown>`, `$effect`, legacy/fallback terms) | 352 lines |
| AI Builder source files matching `ai_builder_*.py` | 120 files, 39,201 LOC |

## LOC Hotspots

| File | LOC | Why It Matters |
|---|---:|---|
| `backend/tests/unittests/flows/test_flow_executor_runtime.py` | 3,707 | Test hotspot; likely mixes runtime lifecycle scenarios and can hide fragile implementation coupling. |
| `backend/tests/unittests/flows/test_flow_router.py` | 3,589 | API contract test hotspot; likely hard to review and split by consumer journey. |
| `backend/tests/unittests/flows/test_flow_run_service.py` | 3,401 | Application service test hotspot; likely indicates large service responsibility. |
| `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py` | 3,270 | AI Builder API regression hotspot; high review cost and scenario coupling. |
| `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py` | 2,663 | Production hotspot; proposal processing, repair, fallback, and edit/create logic need canonical ownership review. |
| `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | 1,813 | Production hotspot; create-mode outline/compile responsibilities need review. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | 1,672 | Production hotspot; includes a 593-line `send_message` function. |
| `backend/src/intric/flows/runtime/executor.py` | 1,456 | Runtime hotspot; includes a 416-line `execute` function and multiple broad catches. |
| `backend/src/intric/flows/api/flow_models.py` | 1,301 | Public API schema hotspot; many boundary contracts and debug/evidence models live in one file. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte` | 1,196 | Frontend state/UI hotspot; run input payload and form state ownership need review. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte` | 1,157 | Frontend editor hotspot; step editing state and persistence boundaries need review. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts` | 992 | AI Builder client/state hotspot; manual protocol parsing and transport typing need review. |

## AI Builder Package Size

| File | LOC | First-Pass Risk |
|---|---:|---|
| `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py` | 2,663 | Proposal processing, repair, edit/create branching, and fallback handling need cluster-level ownership. |
| `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | 1,813 | Create-mode outline generation and compilation likely mix planning and materialization rules. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | 1,672 | Planner turn orchestration and request construction are large enough to hide multiple lifecycle phases. |
| `backend/src/intric/flows/ai_builder/ai_builder_repo.py` | 1,240 | Persistence/session state needs review for JSON contract ownership and transaction boundaries. |
| `backend/src/intric/flows/ai_builder/ai_builder_router.py` | 1,102 | Router surface may mix API adapter, session workflow, and schema concerns. |

## Function Hotspots

| Function | Evidence | LOC | First-Pass Risk |
|---|---|---:|---|
| `send_message` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:944-1536` | 593 | Planner turn orchestration appears too large for one reviewer to reason about safely. |
| `execute` | `backend/src/intric/flows/runtime/executor.py:316-731` | 416 | Runtime lifecycle, cancellation, terminalization, and error handling likely share one large control flow. |
| `analyze_discovery` | `backend/src/intric/flows/ai_builder/ai_builder_discovery.py:119-473` | 355 | Discovery analysis may mix extraction, decisions, and presentation. |
| `resolve_step_input` | `backend/src/intric/flows/runtime/step_input_resolution.py:54-388` | 335 | Input ownership and validation are central to runtime correctness. |
| `_prepare_planner_request` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:488-773` | 286 | Prompt/request construction likely mixes protocol, state, and business rules. |
| `complete_step_execution` | `backend/src/intric/flows/runtime/step_execution_runtime.py:738-1013` | 276 | Step result persistence, evidence, and failure behavior need an explicit lifecycle contract. |

## First-Pass Risk Inventory

| Risk | Evidence | Why It Matters | Phase 1 Owner |
|---|---|---|---|
| Runtime status state machines are closed and duplicated in DB constraints. | Runtime enums at `backend/src/intric/flows/enums.py:64-85`; DB checks at `backend/src/intric/database/tables/flow_tables.py:397-400`, `backend/src/intric/database/tables/flow_tables.py:503-506`, `backend/src/intric/database/tables/flow_tables.py:570-572`; running index at `backend/src/intric/database/tables/flow_tables.py:439-444` | Any human-in-the-loop pause/edit status, pending review status, or retry lifecycle expansion requires coordinated enum, CHECK constraint, index, API, frontend, and audit changes. | Concept invariants/runtime/data/frontend reviewers |
| Published flow definitions are immutable JSONB snapshots with embedded schema version but no first-class DB contract owner. | `definition_json` and checksum live at `backend/src/intric/database/tables/flow_tables.py:231-253`; `schema_version` is embedded by `backend/src/intric/flows/application/flow_service.py:686-697`; runtime parsing accepts `dict[str, Any]` at `backend/src/intric/flows/runtime/step_definition_parser.py:33-42` | Old runs must keep executing old snapshots while new features evolve the JSON shape; contract versioning and migration behavior need one owner. | Data model/API/runtime reviewers |
| Compatibility shim modules preserve parallel import paths. | `backend/src/intric/flows/flow.py:1`, `backend/src/intric/flows/flow_repo.py:1`, `backend/src/intric/flows/flow_run_repo.py:1`, `backend/src/intric/flows/flow_service.py:1`, `backend/src/intric/flows/flow_run_service.py:1`, `backend/src/intric/flows/flow_version_repo.py:1` | Pre-production compatibility paths increase reviewer uncertainty and weaken canonical ownership. | Architecture/canonical ownership reviewer |
| Flow domain JSON contract is a broad `dict[str, Any]` alias. | `backend/src/intric/flows/domain/flow.py:23`, then used on step/run/result fields at `backend/src/intric/flows/domain/flow.py:38-46`, `backend/src/intric/flows/domain/flow.py:143-144`, and `backend/src/intric/flows/domain/flow.py:161-164` | The standard requires typed contracts at boundaries; untyped JSON can become hidden schema. | Data model/API contract reviewers |
| Runtime has many broad catches. | `backend/src/intric/flows/runtime/executor.py:545`, `backend/src/intric/flows/runtime/executor.py:624`, `backend/src/intric/flows/runtime/executor.py:693`, `backend/src/intric/flows/runtime/executor.py:1102`, plus `backend/src/intric/flows/runtime/step_execution_runtime.py:226`, `backend/src/intric/flows/runtime/tasks.py:303` | Broad catches can hide invalid states unless terminalization, logging, retries, and idempotency are explicit. | Runtime reliability reviewer |
| Terminal-state audit logging failure is swallowed. | `backend/src/intric/flows/runtime/executor.py:1089-1111` catches `Exception`, logs a warning, and continues after audit write failure. | Audit coverage is a compliance/operability invariant; swallow-and-warn may be correct, but it needs an explicit owner and failure-mode policy. | Observability/operability reviewer |
| Flow runtime Celery queue and beat schedule need ownership. | Queue name provider at `backend/src/intric/main/container/container.py:400-401`; execution backend queue dispatch at `backend/src/intric/flows/runtime/celery_execution_backend.py:24-79`; Celery routes and beat schedule at `backend/src/intric/flows/runtime/celery_app.py:25-38`; task names at `backend/src/intric/flows/runtime/tasks.py:179` and `backend/src/intric/flows/runtime/tasks.py:362` | Retry, reconciliation, duplicate starts, crash recovery, and local runtime artifacts must be reviewed as one operational system. | Runtime/observability reviewers |
| API schema file centralizes many unrelated contracts. | `backend/src/intric/flows/api/flow_models.py:230`, `backend/src/intric/flows/api/flow_models.py:414`, `backend/src/intric/flows/api/flow_models.py:668`, `backend/src/intric/flows/api/flow_models.py:931`, `backend/src/intric/flows/api/flow_models.py:1044`, `backend/src/intric/flows/api/flow_models.py:1064` | Public contract evolution becomes harder when authoring, runtime, evidence, debug export, and template schemas share one large module. | API contract reviewer |
| Frontend duplicates backend-shaped contracts manually. | `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:45`, `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:100-104`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:276`, `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:46-49` | Manual contracts drift from OpenAPI/generated clients and make API consumer behavior harder to verify. | Frontend state/API reviewer |
| Frontend flow state uses broad records and casts in core editor paths. | `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:36`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:294`, `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:621`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:65` | State ownership and type boundaries are unclear, especially across generated client, driver, service, and components. | Frontend state reviewer |

## Compatibility Shim Reverse-Import Counts

| Shim Import Path | Hits Outside Docs | Evidence | Phase 1 Question |
|---|---:|---|---|
| `intric.flows.flow_service` | 3 | `backend/tests/unittests/flows/test_typed_io_service.py:11`, `backend/tests/unittests/flows/test_flow_service.py:14`, `backend/tests/unittests/flows/test_flow_template_asset_compatibility.py:15` | Can tests import `intric.flows.application.flow_service` directly and delete the shim? |
| `intric.flows.flow_repo` | 0 | No `rg` hits | Delete candidate if no non-grep dynamic import exists. |
| `intric.flows.flow_run_service` | 2 | `backend/tests/unittests/flows/test_flow_run_service.py:27`, `backend/tests/unittests/flows/test_typed_io_run_service.py:17` | Can tests import the application module directly? |
| `intric.flows.flow_run_repo` | 1 | `backend/tests/integration/flows/test_flow_run_repository.py:25` | Can integration tests import the infrastructure module directly? |
| `intric.flows.flow_version_repo` | 0 | No `rg` hits | Delete candidate if no non-grep dynamic import exists. |
| `intric.flows.flow` | 40+ | Production hits include `backend/src/intric/actors/actors/space_actor.py:11`, `backend/src/intric/flows/ai_builder/ai_builder_plan_store.py:23`, `backend/src/intric/flows/ai_builder/ai_builder_dispatcher.py:46`, `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py:33`, `backend/src/intric/flows/ai_builder/ai_builder_repo.py:49`, `backend/src/intric/flows/ai_builder/ai_builder_edit_normalizer.py:28` | This shim is still a live production import path and needs an explicit migration plan, not immediate deletion. |

## Flow-Scoped Frontend Check Diagnostics

| File | Diagnostic | Why Phase 1 Cares |
|---|---|---|
| `frontend/packages/intric-js/src/endpoints/flows.js:440` | `delete normalizedRequest.flow_id` fails because the operand is not optional. | Generated/handwritten client contract around run creation is inconsistent. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/test-harnesses/FlowAIBuilderHarness.svelte:15` | Svelte warns local references capture initial `transport` and `flowId`. | Test harness state may not reflect reactive service initialization. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderEditHost.svelte:18` | Svelte warns local references capture initial `intric`, `spaceId`, and `flowId`. | AI Builder service lifetime ownership is unclear at component boundary. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/FlowsTable.svelte:88` | `resolve(flowPath(flow))` route argument is typed as plain `string`. | Flow route helpers are not preserving SvelteKit route literal types. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/FlowsTable.svelte:133` | Same route-literal type failure. | Duplicate symptom of route helper/API type drift. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/ai-builder/+page.svelte:16` | Svelte warns local reference captures initial `data`. | AI Builder page initializes service from route data with unclear reactivity/lifetime. |

The six rows above are the complete unique flow-scoped file:line diagnostics found by the filtered `pnpm -C frontend check` command, after collapsing duplicate workspace output.

## Test Hotspot Functional Anchors

| File | Longest Local Tests | Largest Local Fixture Signal |
|---|---|---|
| `backend/tests/unittests/flows/test_flow_executor_runtime.py` | `test_execute_persists_distinct_model_parameters_for_each_step` at line 547 is 130 LOC; `test_webhook_failure_keeps_completed_step_evidence` at line 250 is 115 LOC; `test_execute_appends_completed_handoff_and_continues_with_next_step` at line 1759 is 110 LOC. | No local pytest fixtures detected by AST. |
| `backend/tests/unittests/flows/test_flow_router.py` | `test_test_flow_http_applies_ssrf_runtime_guards` at line 361 is 94 LOC; `test_upload_flow_template_file_enforces_scope_and_uses_docx_template_save` at line 821 is 83 LOC; `test_flow_run_evidence_export_alias_fails_closed_when_audit_write_fails` at line 2208 is 82 LOC. | No local pytest fixtures detected by AST. |
| `backend/tests/unittests/flows/test_flow_run_service.py` | `test_get_evidence_redacts_sensitive_values` at line 2585 is 136 LOC; `test_get_evidence_includes_rag_metadata_in_debug_export` at line 2724 is 102 LOC; `test_create_run_persists_expected_version_and_step_inputs` at line 798 is 86 LOC. | No local pytest fixtures detected by AST. |
| `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py` | `test_ai_builder_api_edit_mode_transcription_insert_clears_stale_runtime_input` at line 2816 is 184 LOC; `test_ai_builder_api_create_mode_can_generate_approve_and_apply_a_flow` at line 2424 is 163 LOC; `test_ai_builder_api_edit_mode_output_only_change_updates_description_and_preserves_assistant` at line 2591 is 145 LOC. | `bearer_token` at line 62 is a 5 LOC local fixture; most setup likely lives in imported fixtures/helpers. |

## Acceptance Criteria For Phase 0

| Criterion | Status |
|---|---|
| `docs/refactor/README.md` exists | Done |
| `docs/refactor/phase0/baseline.md` exists | Done |
| `docs/refactor/phase0/repository-map.md` exists | Done |
| `docs/refactor/phase0/maintainability-standards.md` exists | Done |
| Tool availability and blocked tools are documented | Done |
| Failing checks are documented without pretending they are flow-specific | Done |
| Flow-scoped frontend diagnostics are separated from repo-wide frontend breakage | Done |
| LOC hotspots and high-risk terms are documented | Done |
| Claude peer challenge iteration 1 has reviewed Phase 0 before Phase 1 starts | Done; returned `changes_required` |
| Codex has verified and incorporated Claude iteration-1 corrections | Done |
| Claude green-light pass has reviewed the revised Phase 0 before Phase 1 starts | Done; returned `GREEN_LIGHT: yes` |

## Risk And Trade-Off

The baseline is intentionally broad. Some command failures are environmental or repo-wide rather than flow-specific, so they should not be treated as product findings until Phase 1 verifies them against source ownership. The highest-risk Phase 0 trade-off is sequencing: the prompt asks for ten concurrent reviewers, while Claude correctly identified cross-cutting Single Source of Truth risk. The revised plan keeps the required parallel reviewers and adds Phase 1b concept/operability passes before synthesis. Confidence: high for command results and file/line evidence; medium for first-pass risk classification.
