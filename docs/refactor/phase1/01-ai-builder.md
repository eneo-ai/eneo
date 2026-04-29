# Phase 1a Agent A - AI Builder Review

TL;DR:
1. AI Builder is powerful but not yet maintainable: most small modules are reasonably narrow, but proposal processing, planner turn orchestration, router SSE wrapping, frontend driver/service state, and frontend contracts concentrate the risk.
2. The highest-risk ownership gaps are the proposal processor, planner turn orchestration, frontend driver/service state split, and manually duplicated backend/frontend contracts.
3. Planning state is the strongest part of the design: `PlanningState` has a typed persisted home, versioning, overwrite discipline, and integration coverage, but too much surrounding code rebuilds, carries, repairs, and presents that state in the same call paths.
4. Several repair paths are legitimate LLM-boundary hardening; several compatibility/test/fallback paths should be deleted or converted into explicit typed failure modes before they become permanent architecture.
5. Overall score: 3/10, driven by single-source-of-truth and separation-of-concerns risk; refactor required before further AI Builder feature expansion.

## Scope And Inputs

Reviewed scope:

| Area | Included |
|---|---|
| Backend AI Builder | `backend/src/intric/flows/ai_builder/**` |
| Frontend AI Builder | `frontend/apps/web/src/lib/features/flows/ai-builder/**` |
| AI Builder tests | `backend/tests/integration/flows/ai_builder/**`, `backend/tests/integration/flows/test_ai_builder_*`, `backend/tests/unit/test_ai_builder_openapi_contract.py`, `backend/tests/unit/test_ai_builder_plan_edit_context.py`, `backend/tests/unittests/flows/ai_builder/**`, and colocated frontend AI Builder tests |
| Required standards | `docs/engineering/maintainability-standards.md`, `docs/engineering/comment-and-readability-standard.md`, `docs/engineering/api-design-standard.md`, `docs/engineering/testing-standard.md`, `docs/engineering/frontend-state-standard.md` |
| Phase context | `docs/refactor/phase0/*.md`, `docs/refactor/phase1/README.md`, `prompt.md`, `AGENTS.md` |

Constraints followed:

| Constraint | Result |
|---|---|
| Documentation-only | Only this file is intentionally written. |
| No source/test/migration/dependency/generated-client/git changes | No changes proposed as implementation in this pass. |
| Concurrent agents | Other phase docs were not edited. |
| Existing partial doc | No existing `docs/refactor/phase1/01-ai-builder.md` was present before this write. |

## Module Responsibility Map

| Module / cluster | Current responsibility | Current owner | Proposed canonical home | Delete / merge path | Confidence |
|---|---|---|---|---|---|
| `ai_builder_domain_models.py` | Session, plan, spec, envelope, compiled-step, conversation models; claims canonical schema ownership. | AI Builder domain models. | Keep as canonical backend plan/session/spec response contract, but split JSON-bag fields into named value objects where stable. | Delete `ai_builder_models.py` aggregation imports after callers migrate to concrete model modules. | High |
| `ai_builder_api_models.py` | HTTP request/response schemas and OpenAPI examples. | HTTP adapter schema layer. | Keep API-only schemas here; generated frontend types should consume these, not manually duplicate them. | Remove frontend manual duplicates once generated client covers AI Builder. | High |
| `planning_state.py` / `planning_state_builder.py` | Typed persisted planning state and deterministic conversation-to-state rebuild. | Planning-state domain module. | Keep as canonical state lifecycle owner. | Move any remaining planning-state lifecycle mutation out of planner/proposal call paths when it is not prompt assembly. | High |
| `ai_builder_repo.py` | Session, plan, attachment, send-lock, planning-state persistence, conversation persistence. | Persistence adapter. | Keep persistence ownership, but keep lifecycle decisions in application/use-case modules. | Do not add new repository abstractions; reduce row `Any` only where row shape can be typed locally. | High |
| `ai_builder_service.py` | Composition facade, session creation/listing, planner context prep, plan lifecycle delegation, revision inline. | Application facade. | Split actual lifecycle commands to `AIBuilderPlanLifecycle`; keep service as composition boundary only if it stops owning domain behavior. | Move `revise_plan` into plan lifecycle; delete delegation-only tests that assert internal forwarding. | High |
| `ai_builder_planner.py` | Send-message lifecycle, lease, conversation mutation, planning-state rebuild, prompt prep, action policy, LLM turn, telemetry, SSE events. | Planner turn coordinator by accident. | Introduce one deep planner-turn use case that owns lock/commit/error semantics and subordinate prompt prep / event presentation modules with narrow typed interfaces. | Move request preparation and event presentation out of the lock/commit core; delete compatibility required-slot fallback after tests migrate. | High |
| `ai_builder_orchestration_pipeline.py` / `ai_builder_planner_turn.py` | Planner LLM call, parse/semantic repair, dispatch turn persistence. | Planner pipeline. | Keep as canonical LLM-boundary repair and accepted/rejected outcome owner. | Expose typed telemetry and failure taxonomy so planner does not reclassify generic dict diagnostics. | Medium |
| `ai_builder_proposal_processor.py` | Proposal LLM tool call, create/edit processing, validation, repair, persistence, plan events, retry loops. | Proposal processor by accident. | Split by real boundary: proposal transport/retry, create proposal processor, edit proposal processor, plan persistence/presentation. | Move create/edit logic into existing create/edit modules; replace `process_tool_kwargs: dict[str, Any]` with typed commands. | High |
| Create modules: `ai_builder_create_models.py`, `ai_builder_create_outline.py`, compiler/validator/normalizer/dataflow | LLM-facing create outline, compile to create draft, validate, normalize, compile final spec. | Create proposal domain. | Keep as create-mode canonical owner; rename legacy-stripping paths as LLM-boundary normalization. | Move create-specific branches out of `AIBuilderProposalProcessor`. | High |
| Edit modules: `ai_builder_edit_models.py`, compiler/validator/normalizer/tool schema/scope | LLM-facing edit IR, validation, compilation, diff/advisory surface. | Edit proposal domain. | Keep as edit-mode canonical owner; move revision status/approve/apply adjacency into plan lifecycle. | Move edit-specific branches out of `AIBuilderProposalProcessor` and service `revise_plan`. | High |
| `ai_builder_plan_store.py` | Build plan envelope, append assistant/tool messages, persist plan and planning state. | Plan persistence helper. | Either make this the canonical plan-proposal persistence use case or fold it into a plan proposal module; avoid a generic helper shape. | Replace `validation: Any`, `arguments: dict[str, Any]`, `edit_result_json: dict[str, Any]` with typed inputs. | Medium |
| `ai_builder_plan_lifecycle.py` | Approve/apply plans, validate revisions, compile and execute changesets, rollback status on apply failure. | Plan lifecycle use case. | Canonical home for approve/apply/revise and apply attempt state. | Move `AIBuilderService.revise_plan` here; add explicit failed/apply-attempt recovery state. | High |
| `ai_builder_materializer.py` | Compile approved spec to changeset and execute flow mutations through `FlowService`. | Materialization adapter/use case blend. | Keep compile half as pure materialization domain; move mutation sequencing into an application-layer apply transaction/recovery owner. | Replace `flow_service: Any`; add crash recovery for temp flow and partially configured assistants. | High |
| `ai_builder_router.py` | HTTP routes, permission checks, scope checks, audit, SSE wrapping, usage-event fallback, error translation. | FastAPI adapter. | Keep HTTP parsing/error translation; move visibility filtering and stream post-processing policy to application/service. | Delete router test compatibility helpers after tests stop importing private helpers. | High |
| `ai_builder_events.py` / `ai_builder_event_models.py` | SSE event payload builders and event Pydantic models. | Event contract module. | Canonical backend SSE payload owner; pair with generated or explicitly versioned frontend event decoder. | Replace dict payload builders with typed event union when practical. | Medium |
| Frontend `protocol.ts` | Manual AI Builder session, plan, spec, event, error, telemetry, revision, chat types. | Frontend local protocol. | Generated client types from OpenAPI for HTTP schemas; a narrow explicit SSE-event adapter for streaming-only types. | Delete manual status/spec/session duplicates after generated types exist. | High |
| Frontend `FlowAIBuilderDriver.ts` | Transport, state owner, stream parser, message hydration, derived phase, plan/apply/revise actions. | Frontend driver. | Make either the driver or service the only state owner; preferred: service/store owns Svelte state, driver becomes transport/parser. | Move derived UI state and filters out of driver if driver remains transport-only. | High |
| Frontend `FlowAIBuilderService.svelte.ts` | Svelte context wrapper, duplicated state mirror, derived guards, pass-through methods. | Svelte service wrapper. | Canonical Svelte state owner if retained. | Delete duplicated mirror or fold driver into service. | High |
| Frontend components | Chat, input, plan pane, step card, question UI. | View layer. | Keep components presentational; move domain parsing/phase/status rules to single state owner. | Extract only repeated UI primitives; do not add generic helpers. | Medium |
| Tests | Broad unit/integration/component coverage, plus large mock-heavy service/router/proposal suites. | Test suite. | Behavior-focused tests at real seams: API, planner turn, proposal compile, persistence, frontend state. | Delete compatibility/delegation tests as code paths are removed. | High |

## Module Depth Analysis

| Module | Depth verdict | Evidence | Problem | Proposed canonical home / fix | Confidence |
|---|---|---|---|---|---|
| `planning_state.py` | Deep module | It declares itself the persisted `PlanningState` home and documents JSONB ownership/versioning at `backend/src/intric/flows/ai_builder/planning_state.py:1`; strict model config forbids extra fields at `backend/src/intric/flows/ai_builder/planning_state.py:84`. | Good owner, but consumers still rebuild/carry/persist state across large planner/proposal paths. | Preserve; surround with smaller lifecycle use cases. | High |
| `planning_state_builder.py` | Deep module | It states it is the single path from conversation to stamped state at `backend/src/intric/flows/ai_builder/planning_state_builder.py:1`; it builds state from conversation at `backend/src/intric/flows/ai_builder/planning_state_builder.py:79`; it carries forward persisted planner-owned fields at `backend/src/intric/flows/ai_builder/planning_state_builder.py:119`. | This is the right kind of concentrated logic. | Keep and use as the only rebuild path. | High |
| `ai_builder_orchestration_pipeline.py` | Mostly deep | The docstring cleanly separates run from dispatch and explains retry accounting at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:1`; accepted/rejected/parse_failed outcomes are explicit at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:72`. | Still accepts `litellm_client: Any`, `litellm_kwargs: dict[str, Any]`, and raw message dicts at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:127`. | Keep owner; add typed LLM request/response wrapper later. | Medium |
| `ai_builder_service.py` | Shallow facade plus leaked domain behavior | The file says it is intentionally a small facade at `backend/src/intric/flows/ai_builder/ai_builder_service.py:1`; `send_message`, `approve_plan`, and `apply_plan` delegate at `backend/src/intric/flows/ai_builder/ai_builder_service.py:459` and `backend/src/intric/flows/ai_builder/ai_builder_service.py:548`, while `revise_plan` is implemented inline at `backend/src/intric/flows/ai_builder/ai_builder_service.py:562`. | It is neither a pure composition root nor the plan lifecycle owner. | Keep composition here; move revision into `AIBuilderPlanLifecycle`; delete pure delegation tests. | High |
| `ai_builder_router.py` | Thick adapter | Private test seam at `backend/src/intric/flows/ai_builder/ai_builder_router.py:116`; visibility filtering loops over sessions and space permissions at `backend/src/intric/flows/ai_builder/ai_builder_router.py:414`; nested SSE usage/done/error policy lives at `backend/src/intric/flows/ai_builder/ai_builder_router.py:521`. | HTTP adapter now owns policy that is hard to reuse or test as application behavior. | Keep HTTP shape/error mapping; move visibility and stream completion policy behind service/use-case methods. | High |
| `ai_builder_proposal_processor.py` | Overloaded deep module | Proposal context combines LLM messages, tool schemas, refs, catalog, flow, snapshots, planning state, lease, and revision context at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:372`; create outline processing compiles, validates, and persists at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:466`; edit processing handles parse/validate/compile/MCP/repair at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2054`. | It hides complexity, but its interface is almost as complex as its implementation. | Split along create/edit/proposal transport/plan persistence boundaries. | High |
| `FlowAIBuilderService.svelte.ts` | Pass-through with duplicated state | It mirrors 14 driver state fields as `$state` at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:30`; most methods pass through to the driver at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:169`; `#applyState` copies every field from driver state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:266`. | Two state owners exist for the same UI concepts. | Make service the only Svelte state owner and driver transport-only, or delete the service mirror. | High |
| `FlowAIBuilderDriver.ts` | Overloaded frontend application service | It owns state shape at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45`; it parses SSE events and mutates session/plan/messages at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:378`; it hydrates backend conversation into UI messages at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:810`; it derives UI phase at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:649`. | Transport, parser, state machine, and UI derivation are tangled. | Split into transport/event decoder and one state store. | High |

## Files Over 400 LOC

Inventory source: direct `wc -l` over backend AI Builder and frontend AI Builder source files. This table intentionally includes every source/UI file above 400 LOC in scope.

| File | LOC | Distinct responsibilities observed | Proposed split / deepening | Confidence |
|---|---:|---|---|---|
| `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py` | 2663 | LLM proposal call, tool-call parsing, create/edit validation, resource canonicalization, self-correction, plan persistence, SSE events. | Split into proposal transport/retry, create proposal processor, edit proposal processor, plan event/persistence adapter. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | 1813 | LLM-facing outline schema, legacy/LLM normalization, planning-state context projection, pattern-chain application, compile to create draft, tool schema generation. | Keep as create-outline owner; extract schema generation only if it becomes a stable public contract module. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_planner.py` | 1672 | Send lock, planning-state rebuild, prompt prep, server action policy, LLM dispatch, telemetry, event emission. | Split planner turn coordination from prompt preparation and event presentation. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_repo.py` | 1240 | Sessions, plans, attachments, conversation compaction, lock lease, planning-state CAS, row conversion. | Keep repository owner; move lifecycle decisions out; consider typed row mappers. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_router.py` | 1102 | HTTP routes, permission, scope, audit, SSE wrapping, usage fallback, error examples. | Keep adapter; move visibility filtering and stream completion policy into service/use case. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py` | 1057 | Existing-flow snapshot mapping, edit operation compilation, diff, comparable payloads, metadata patches. | Keep edit compiler; split only if by edit lifecycle phase with stable interfaces. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_framework_policy.py` | 1045 | Semantic extraction, output/input intent policy, mode detection, freeform aggregation. | Keep policy owner; split by concept only if signal families are independently testable. | Medium |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts` | 992 | Transport, state, SSE parser, plan/apply/revise actions, hydration, derived phase. | Make driver transport/parser-only or fold into service as sole state owner. | High |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte` | 913 | Chat composer, file input, edit context, focus signature compatibility, submit UX. | Keep component but extract stable uploader/input primitives if repeated elsewhere. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py` | 862 | Plan quality/critic invariant rules. | Keep if tests exercise behavior; ensure failures map to typed warning codes. | Medium |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts` | 844 | Driver state, streaming, telemetry, recovery behavior. | Keep behavior coverage; update after state owner consolidation. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_materializer.py` | 813 | Spec-to-changeset compiler and mutation executor. | Split pure compiler from side-effect executor/recovery owner. | High |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte` | 804 | Review pane, diff rendering, state latches, action bar, empty/progress states. | Keep view; move domain derivations to state owner if not display-specific. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery.py` | 793 | Discovery analysis and question selection. | Keep unless duplicated with question catalog. | Medium |
| `backend/src/intric/flows/ai_builder/pattern_registry.py` | 765 | Pattern registry. | Keep as registry if single source of pattern truth. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_mcp_intent.py` | 742 | MCP intent/selection behavior. | Keep; watch overlap with resource catalog and proposal processor. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery_questions.py` | 691 | Discovery question definitions/selection. | Keep if question catalog does not duplicate canonical IDs. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_prompts.py` | 676 | Prompt construction and plan summaries. | Keep prompt ownership; version prompt contracts. | Medium |
| `backend/src/intric/flows/ai_builder/question_catalog.py` | 665 | Question catalog. | Confirm relationship to discovery questions; avoid two question registries. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_service.py` | 657 | Composition, session lifecycle, context prep, delegation, revision. | Move revision; reduce to composition/application facade. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery_issue_rules.py` | 647 | Discovery issue rules. | Keep if used by one discovery owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_orchestrator.py` | 612 | Planner output parsing/evaluation/orchestration context. | Keep as planner action contract owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_input_architecture_policy.py` | 590 | Input architecture policy. | Keep policy owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` | 585 | Proposal repair/self-correction. | Merge retry logic out of proposal processor into here if this is the repair owner. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_resource_catalog.py` | 583 | Model/KB/MCP resource catalog and references. | Keep as resource canonicalization support. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_knowledge_pack_core.py` | 577 | Knowledge pack behavior. | Keep if scoped to knowledge packs. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_flow_context.py` | 540 | Existing-flow context projection. | Keep as edit context projection owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_repair.py` | 537 | Planner repair helpers. | Keep as planner repair owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery_decision_engine.py` | 536 | Discovery decision engine. | Confirm with discovery module; avoid split-brain question selection. | Medium |
| `backend/src/intric/flows/ai_builder/deterministic_signals_extractor.py` | 515 | Deterministic signal extraction. | Keep signal extraction owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_runtime_input_fields.py` | 500 | Runtime input field derivation. | Keep if canonical for runtime input fields. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_step_transition_policy.py` | 488 | Step transition rules. | Keep as policy owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py` | 460 | Planner LLM call and repair pipeline. | Keep; add typed LLM request later. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py` | 442 | Backend canonical domain/API plan/session models. | Keep; reduce JSON bags where stable. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_materialization_bridge.py` | 435 | Bridge to materialization. | Confirm it is not pass-through once materializer is split. | Medium |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderStepCard.svelte` | 434 | Step display details. | Keep display component. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py` | 434 | Outline pattern chain. | Keep if canonical chain owner. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_discovery_profile_builder.py` | 431 | Discovery profile building. | Confirm with flow context/discovery. | Medium |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py` | 417 | Edit validation. | Keep edit validation owner. | Medium |
| `backend/src/intric/flows/ai_builder/planning_state_builder.py` | 416 | Conversation-to-planning-state rebuild. | Keep. | High |
| `backend/src/intric/flows/ai_builder/ai_builder_plan_edit_context.py` | 415 | Plan edit context. | Keep if canonical for scoped plan edits. | Medium |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderQuestion.svelte` | 407 | Structured question UI. | Keep display component. | Medium |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte` | 401 | Chat transcript UI. | Keep display component. | Medium |

## Hotspot Analysis

### `ai_builder_proposal_processor.py`

| Required field | Assessment |
|---|---|
| Problem | `AIBuilderProposalProcessor` is the biggest AI Builder file and mixes proposal LLM transport, tool-call handling, create/edit parse/validate/compile logic, resource canonicalization, self-correction, plan persistence, lease-aware commits, and SSE event generation. |
| Why it matters | It is hard to review a plan-proposal change safely because the reviewer must reason across LLM call behavior, create/edit domain rules, persistence side effects, and streaming presentation in one module. |
| Evidence | `ProposalContext` includes transport, tool schema, resource, flow, snapshot, planning-state, lease, and revision fields at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:372`; `ToolRetryConfig` stores untyped `process_tool_kwargs` at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:409`; create outline parsing and compilation begin at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:466`; proposal LLM transport starts at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:933`; edit parsing/validation/compilation/MCP/description repair starts at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2054`. |
| Current owner | `AIBuilderProposalProcessor`. |
| Proposed canonical home | Proposal transport/retry in a proposal task module; create processing in create modules; edit processing in edit modules; plan persistence in a plan-proposal persistence use case. |
| Delete / merge path | Move create-only code to a create proposal processor using `FlowCreateDraft`; move edit-only code to an edit proposal processor using `FlowEditDraft`; merge retry/process kwargs into typed commands; replace the success/failure bag `ToolProcessingResult` with a discriminated union; delete generic callable+dict dispatch once both paths are explicit. |
| Acceptance criteria | A reviewer can follow create proposal, edit proposal, and LLM retry independently; no create/edit processing path accepts generic `dict[str, Any]` except the first LLM boundary parse; all plan persistence goes through one typed command. |
| Tests required | Behavior tests for create proposal success/failure, edit proposal success/failure, resource-resolution feedback, MCP clarification, scoped revision rejection, self-correction retries, and plan event payloads. |
| Risk / trade-off | Splitting too aggressively could create shallow files; split only at boundaries with separate invariants and test surfaces. |
| Human reviewability impact | High improvement: proposal diffs become local to create, edit, or transport. |
| Confidence | High. |

Additional typed-result finding:

| Required field | Assessment |
|---|---|
| Problem | `ToolProcessingResult` conflates success and failure shapes. |
| Why it matters | Callers must remember conventions instead of getting type-checker help; a result can technically carry both events and feedback. |
| Evidence | `ToolProcessingResult` has optional `event`, `events`, `feedback`, and `failure_kind` fields at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:295`; the edit path returns validation failures and event results from the same type at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2077` and `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2202`. |
| Current owner | `AIBuilderProposalProcessor`. |
| Proposed canonical home | Proposal submission result model near the proposal submission processors. |
| Delete / merge path | Replace with `SubmissionOk(events)` / `SubmissionFailure(feedback, kind)` or equivalent tagged Pydantic/dataclass union. |
| Acceptance criteria | A result cannot express both success and failure; all call sites exhaustively match on the discriminant. |
| Tests required | Existing proposal processor tests should assert success/failure outcomes through the discriminant. |
| Risk / trade-off | Low; mostly mechanical but touches many call sites. |
| Human reviewability impact | Medium-high. |
| Confidence | High. |

### `ai_builder_planner.py`

| Required field | Assessment |
|---|---|
| Problem | `send_message` owns the whole planner turn: budget defaults, session status, lock/lease, edit context, planning-state load/rebuild, metadata resolution, prompt preparation, server-discovery shortcuts, action-policy fallback, LLM dispatch, telemetry, error event mapping, chained actions, and lease release. |
| Why it matters | Locking, persistence, and event presentation are reliability-sensitive. Combining them with prompt assembly makes it easy to introduce subtle ordering bugs. |
| Evidence | Prepared request fields span requirements, UI language, discovery, LLM messages, rebuilt planning state, action policy, server output, prompt hash, proposal mode, edit context, and prior plan at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:211`; `_prepare_planner_request` builds discovery, flow context, resource context, planning state, action policy, server output, prompt, and trimming at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:488`; `send_message` claims a send lock and starts a lease at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:994`; the same method builds orchestration context and handles compatibility required slots at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1151`; it runs the planner and maps failures to SSE at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1295`; it emits telemetry and planner events at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1369`; it releases the lease at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1519`. |
| Current owner | `AIBuilderPlanner`. |
| Proposed canonical home | `AIBuilderPlannerTurn` or equivalent application use case owns lock, turn transaction, and terminal outcomes; prompt prep and event presentation become subordinate deep modules. The lease should become an active turn context instead of a pair of tokens threaded through proposal methods. |
| Delete / merge path | Delete compatibility required-slot fallback after tests/callers stop depending on it; avoid new fake interfaces around LLM calls; remove `lease_request_id` / `lease_lock_token` from proposal method signatures once the turn context owns write authorization. |
| Acceptance criteria | Lock/lease lifecycle is readable without prompt code; prompt assembly is testable without session locks; event mapping is typed and consistent for planner/proposal errors; lease tokens are not passed through every proposal helper. |
| Tests required | Planner-turn behavior tests for lease lost, parse failure, rejected output, server output, proposal handoff, chained confirm requirements, and planning-state version mismatch. |
| Risk / trade-off | Moving code can obscure ordering; do it as behavior-preserving moves before changing behavior. |
| Human reviewability impact | High improvement for reliability-sensitive diffs. |
| Confidence | High. |

Lease-plumbing finding:

| Required field | Assessment |
|---|---|
| Problem | Lease tokens are persisted correctly but leak through too many proposal signatures. |
| Why it matters | Every new proposal subpath must remember to thread the same two parameters through to repository writes, increasing both call noise and missed-write risk. |
| Evidence | Repository send-lock fields live on `BuilderSessions` at `backend/src/intric/database/tables/flow_tables.py:697`; the repository claims, refreshes, and releases the lease at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:646`, `backend/src/intric/flows/ai_builder/ai_builder_repo.py:685`, and `backend/src/intric/flows/ai_builder/ai_builder_repo.py:714`; proposal processor method signatures and calls thread `lease_request_id` / `lease_lock_token` repeatedly, including `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:480`, `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:582`, `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:956`, and `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2072`. |
| Current owner | Planner turn plus repository CAS filters. |
| Proposed canonical home | A typed active turn context owned by the planner turn use case. |
| Delete / merge path | Keep DB CAS filters; pass a single typed `ActivePlannerTurn` or repo-bound context to persistence methods instead of raw token pairs. |
| Acceptance criteria | Proposal processors cannot forget a lease token because they do not receive token pairs directly. |
| Tests required | Lease-lost and concurrent-send tests through planner turn and proposal persistence. |
| Risk / trade-off | Medium; touches reliability-sensitive paths. |
| Human reviewability impact | Medium-high. |
| Confidence | High. |

### `ai_builder_router.py`

| Required field | Assessment |
|---|---|
| Problem | The router is a thick adapter: it owns HTTP schema, permissions, scope compatibility, visibility filtering, audit, SSE post-processing, usage-event fallback, and broad stream error mapping. |
| Why it matters | API adapter code becomes hard to review because user-visible behavior is mixed with HTTP ceremony. |
| Evidence | Test compatibility helper `_resolve_litellm_params` is kept in the router at `backend/src/intric/flows/ai_builder/ai_builder_router.py:116`; `_ROUTER_TEST_COMPAT_HELPERS` exists only to preserve private helpers at `backend/src/intric/flows/ai_builder/ai_builder_router.py:237`; `list_sessions` loops through sessions, loads spaces, catches not-found, and filters permissions at `backend/src/intric/flows/ai_builder/ai_builder_router.py:414`; `send_message` builds a nested SSE stream and injects usage/done/error behavior at `backend/src/intric/flows/ai_builder/ai_builder_router.py:521`. |
| Current owner | FastAPI router. |
| Proposed canonical home | Router keeps dependency/auth parsing and HTTP error translation; application/service owns visible-session query and stream completion policy. |
| Delete / merge path | Delete router test compatibility helpers; rewrite tests through public endpoints or service behavior. |
| Acceptance criteria | Router handlers read as parse/check/call/translate; no private router helper is imported by tests; SSE stream policy has direct unit tests outside FastAPI. |
| Tests required | API contract tests for operation IDs, response models, errors; service/use-case tests for session visibility and usage-event fallback. |
| Risk / trade-off | Moving scope checks out of router would be wrong; keep authentication/authorization enforcement visible at adapter boundary. |
| Human reviewability impact | Medium-high. |
| Confidence | High. |

### `FlowAIBuilderDriver.ts`

| Required field | Assessment |
|---|---|
| Problem | The driver is both transport and frontend application state machine. |
| Why it matters | Frontend state has two owners with the Svelte service, and backend contract changes must be updated in a manually parsed/cast event pipeline. |
| Evidence | Transport accepts `unknown` init and returns `unknown` at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:35`; driver owns full state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45`; recoverable draft filtering is implemented here at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:235`; SSE parsing/casts and state mutation occur at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:378`; phase derivation occurs at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:649`; backend conversation hydration parses tool calls and metadata at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:810`; plan status defaults to `"proposed"` when missing at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:957`. |
| Current owner | `FlowAIBuilderDriver`. |
| Proposed canonical home | Svelte service/store owns state; driver becomes typed HTTP/SSE transport and event decoder. |
| Delete / merge path | Delete duplicate filters and derived state from the driver if the service owns state; delete plan status fallback once generated contract makes status required. |
| Acceptance criteria | One object owns session/messages/currentPlan/status/apply state; transport methods return typed results; stream events are decoded before state mutation. |
| Tests required | Frontend state behavior tests for stream events, reconnect/refresh, draft recovery, apply conflict, revise plan, and hydration from conversation. |
| Risk / trade-off | A pure transport driver may still need a typed event decoder; do not move parsing into components. |
| Human reviewability impact | High. |
| Confidence | High. |

### `FlowAIBuilderService.svelte.ts`

| Required field | Assessment |
|---|---|
| Problem | The service mirrors the driver's state and mostly delegates methods back to the driver. |
| Why it matters | Svelte reactivity is compensating for unclear ownership; every state field now has at least two places to inspect. |
| Evidence | `$state` mirrors session, messages, plan, streaming, initializing, errors, conflict, status, models, and drafts at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:30`; constructor casts the generated client through `unknown` to `AIBuilderClientTransport` at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:63`; recoverable draft filtering duplicates the driver at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:132`; comments state the driver holds source-of-truth derivation while the service touches reactive fields at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:147`; `#applyState` copies every field from driver state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:266`. |
| Current owner | Svelte service wrapper. |
| Proposed canonical home | Make this the single frontend state owner, with a typed transport collaborator. |
| Delete / merge path | Delete the driver-owned mutable state or delete the service mirror; do not keep both. |
| Acceptance criteria | No duplicated state fields; no duplicated recoverable draft filter; no comments about touching state to force reactivity. |
| Tests required | Service/store behavior tests for derived guards and phase transitions. |
| Risk / trade-off | Svelte state is framework-specific; keep transport/domain parsing framework-free. |
| Human reviewability impact | High. |
| Confidence | High. |

## Planning State Lifecycle

| Lifecycle phase | Current path | Evidence | Finding | Proposed canonical home | Acceptance criteria | Tests required | Risk / trade-off | Confidence |
|---|---|---|---|---|---|---|---|---|
| Created | Empty typed state and newly created sessions. | `PlanningState.empty()` builds the empty state at `backend/src/intric/flows/ai_builder/planning_state.py:205`; session creation initializes persisted session rows in the repository create path at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:89`. | Clear enough. | `planning_state.py` plus session creation use case. | New sessions have predictable empty planning state or explicit null-before-first-turn behavior. | Session creation integration tests. | Low. | High |
| Rebuilt from conversation | Deterministic slot surface from conversation plus optional flow context. | `build_planning_state_from_conversation` owns rebuild at `backend/src/intric/flows/ai_builder/planning_state_builder.py:79`; planner calls it during request prep at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:553`; plan store rebuilds after persisting proposal messages at `backend/src/intric/flows/ai_builder/ai_builder_plan_store.py:203`. | Good single rebuild function, but called from many lifecycle owners. | `planning_state_builder.py`; callers should be explicit lifecycle phases. | All rebuilds go through this function; no hidden second resolver. | Rebuild unit tests and commit/proposal persistence integration tests. | Medium. | High |
| Carries forward planner-owned fields | Persisted architecture commit, draft plan id, and monotonic phase preserved. | `carry_forward_persisted_planner_state` documents the overwrite hazard at `backend/src/intric/flows/ai_builder/planning_state_builder.py:119`; planner uses it at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:557`; plan store uses it at `backend/src/intric/flows/ai_builder/ai_builder_plan_store.py:206`. | Necessary but easy to misuse because it mutates in place and appears in multiple persistence paths. | Planning-state lifecycle command. | Carry-forward is invoked once per turn/proposal commit and covered by drift tests. | Tests for monotonic phase, draft plan preservation, architecture commit preservation. | Medium. | High |
| Persisted | JSONB state, version, phase, architecture hash, timestamp. | DB columns exist at `backend/src/intric/database/tables/flow_tables.py:709`; repo `save_planning_state` handles version CAS at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:851`; repo `commit_turn` appends conversation and saves planning state atomically at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:973`. | This is strong; repository is the correct persistence owner. | `AIBuilderRepository`. | No partial JSONB mutation; version mismatch has explicit failure code. | Existing integration tests around `planning_state_version_mismatch` and byte-identical round trips. | Low. | High |
| Validated | Strict Pydantic model and storage serialization. | Strict model config forbids extras at `backend/src/intric/flows/ai_builder/planning_state.py:84`; `load_planning_state` validates JSONB at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:932`; `_planning_state_for_storage` validates snapshot before write at `backend/src/intric/flows/ai_builder/ai_builder_repo.py:1213`. | Strong typed boundary. | `PlanningState` and repository row mapper. | Corrupt state fails explicitly, not silently repaired. | Corruption tests if not already present. | Low. | High |
| Repaired / recovered | LLM parse/semantic repair exists; planning-state carry-forward avoids overwrites. | Planner pipeline retry semantics are documented at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:1`; planner emits parse/rejected failure events at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1415`; carry-forward prevents rebuild erasure at `backend/src/intric/flows/ai_builder/planning_state_builder.py:126`. | LLM repair is mostly explicit; state recovery is spread across planner, repo, and plan store. | Planner pipeline for LLM repair; planning-state lifecycle owner for state preservation. | Repair attempts are visible in telemetry; state carry-forward cannot silently hide invalid persisted data. | Telemetry tests and drift tests. | Medium. | Medium |

## Repair, Compatibility, And Fallback Inventory

| Path | Evidence | Verdict | Would build from scratch today? | Current owner | Proposed canonical home | Delete / merge path | Acceptance criteria | Tests required | Risk / trade-off | Confidence |
|---|---|---|---|---|---|---|---|---|---|---|
| Planner parse/semantic repair loop | Retry accounting and parse handling documented at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:1`; parse repair path starts at `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py:202`. | Keep. | Yes, because LLM output is unreliable. | Planner orchestration pipeline. | Same module, with typed telemetry/failure events. | None now. | Repair budget, parse failed, rejected, drift blocked. | Risk of hiding invalid prompts; mitigated by explicit rejected/parse_failed outcomes. | High |
| Proposal self-correction/repair | Proposal repair module exists; proposal processor invokes repair completion at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:993`. | Keep but move retry orchestration out of giant processor. | Yes, for LLM tool-call boundary. | Proposal processor plus repair module. | Proposal repair module/task. | Merge retry config into typed command. | Retry behavior remains observable and bounded. | Proposal repair success/exhaustion tests. | Medium. | Medium |
| Outline normalization stripping backend-owned/legacy low-level keys | `_normalize_outline_arguments` strips legacy low-level mechanics at `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:387`. | Rewrite naming. | Yes as LLM-boundary normalization, no as permanent "legacy" compatibility. | Create outline module. | Create outline parser. | Rename/document as LLM normalization; delete user compatibility framing. | Normalization is limited to first LLM parse boundary. | Parser tests for malformed LLM payloads. | Low. | Medium |
| Planner required-slot compatibility fallback | Compatibility comment at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1174`. | Delete after test/caller migration. | No. | Planner. | Action policy. | Replace tests/callers with action-policy expectations. | No compatibility fallback in planner turn. | Planner action policy behavior tests. | Medium. | High |
| Router test compatibility helpers | `_resolve_litellm_params` comment at `backend/src/intric/flows/ai_builder/ai_builder_router.py:116`; `_ROUTER_TEST_COMPAT_HELPERS` at `backend/src/intric/flows/ai_builder/ai_builder_router.py:237`. | Delete. | No. | Router. | Public endpoint/service tests. | Remove private helper exports and update tests. | Tests do not import router internals. | Router API tests through app/client. | Low. | High |
| Frontend plan status fallback | `#normalizePlan` defaults missing status to `"proposed"` at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:957`. | Delete once generated contract is used. | No, if `status` is required in API. | Driver. | Generated `PlanResponse` / event decoder. | Fail/decode error on missing required status. | No silent missing status. | Frontend event decoder tests. | Low. | High |
| Frontend apply-error HTTP-status fallback | Fallback maps HTTP 409 to stale revision at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:588`; backend already returns `stale_revision` at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:273`. | Rewrite to typed error decoder. | Maybe, but not as untyped fallback. | Driver. | Shared API error decoder. | Replace status-only fallback with typed backend error model. | Unknown error shapes surface as unknown, not guessed domain codes. | Apply conflict UI tests. | Low. | Medium |
| Materializer temp-flow cleanup fallback | Create mode creates a temp flow at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:233` and attempts cleanup on exception at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:362`. | Rewrite into explicit recovery. | Yes, but with persisted apply attempt/reconciliation. | Materializer executor. | Plan lifecycle/apply recovery owner. | Add apply attempt or cleanup job; do not rely only on in-process catch. | Crash after temp flow creation has recovery path. | Crash/retry integration tests. | High reliability payoff. | High |
| Checked-in `__pycache__` under source/test trees | Source pyc files exist under `backend/src/intric/flows/ai_builder/__pycache__/...`; test pyc files appear in AI Builder test inventory. | Delete from repository. | No. | Repository hygiene. | `.gitignore` / cleanup. | Delete pyc artifacts in implementation phase. | `rg --files '*__pycache__*'` returns none for tracked repo. | No behavior tests; repository hygiene check. | Low. | High |

## AI Builder Contract Review

| Contract | Current shape | Evidence | Finding | Proposed canonical home | Acceptance criteria | Tests required | Confidence |
|---|---|---|---|---|---|---|---|
| HTTP API schemas | Pydantic request/response models in `ai_builder_api_models.py`. | `CreateSessionRequest`, `SendMessageRequest`, `ApplyPlanRequest`, and `RevisePlanRequest` at `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:186`; `PlanResponse` wraps `PlannerPlanEnvelope` at `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:328`. | Good backend owner, but frontend mostly ignores generated types. | `ai_builder_api_models.py` plus generated client. | Frontend imports generated session/plan/apply types. | OpenAPI contract tests and frontend type checks. | High |
| SSE event contract | Backend event payload models plus dict builders. | Event data models at `backend/src/intric/flows/ai_builder/ai_builder_event_models.py:14`; event constants/builders at `backend/src/intric/flows/ai_builder/ai_builder_events.py:22`. | Better than raw dicts, but no generated frontend event union. | `ai_builder_events.py` / event models plus frontend decoder. | One typed event union and one decoder; no ad hoc JSON casts in state mutation. | Backend event payload tests and frontend decoder tests. | Medium |
| Plan/spec/envelope | Backend domain models plus frontend manual duplicate. | Backend `PlannerPlanEnvelope` says storage strips/re-hydrates spec at `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:253`; frontend duplicates `StepSpec`, `FlowDraftSpecCore`, and `PlannerPlanEnvelope` at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:85`. | Single source of truth violation. | Backend Pydantic/OpenAPI schemas; generated TS. | Only streaming-specific additions remain manual. | Contract test that generated schema includes required plan fields. | High |
| Create proposal contract | LLM-facing `FlowCreateOutline`, compiled to `FlowCreateDraft`, then final spec. | `FlowCreateDraft` is strict extra-forbid at `backend/src/intric/flows/ai_builder/ai_builder_create_models.py:49`; outline compile starts at `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py:510`. | Good domain layering, but proposal processor still owns too much orchestration around it. | Create modules. | Create proposal processor delegates to create domain through typed command. | Create compile/validate behavior tests. | High |
| Edit proposal contract | LLM-facing `FlowEditDraft`, compiled to `CompiledEditResult`. | Edit IR purpose is documented at `backend/src/intric/flows/ai_builder/ai_builder_edit_models.py:1`; `FlowEditDraft` starts at `backend/src/intric/flows/ai_builder/ai_builder_edit_models.py:145`; compiled result starts at `backend/src/intric/flows/ai_builder/ai_builder_edit_models.py:233`. | Good concept boundary; still has JSON bags and old/new `Any` in diff fields. | Edit modules. | Stable patch and diff value objects for fields now known. | Edit compiler and API payload tests. | Medium |
| Revision contract | One literal revision type. | Backend `RevisePlanRequest` is `Literal["keep_current_description"]` at `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:241`; frontend duplicates it at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:177`; service implements revision inline at `backend/src/intric/flows/ai_builder/ai_builder_service.py:562`. | Contract is small, but ownership is wrong and duplicated. | `AIBuilderPlanLifecycle`. | Generated frontend type; revision behavior in lifecycle. | Revision API and lifecycle tests. | High |
| Apply contract and failure modes | Plan lifecycle validates, sets applying, materializes, rolls back status on exception. | Session status set to applying at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:133`; broad exception rollback at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:162`; rollback swallows/logs failure at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:315`; temp flow cleanup is catch-only at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:362`. | Failure mode is not explicit enough for worker/process crash or partial side effects. | Plan lifecycle/apply recovery owner. | Persisted apply attempt or explicit failed/recoverable state; reconciliation for created temp flow. | Crash/retry/apply conflict tests. | High |
| Prompts and planner contract versions | Prompt hash and planner schema/version constants logged. | Planner output schema hash comment at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:156`; planner telemetry logs prompt/schema/registry versions at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1385`. | Good observability. | Prompt and planner contract modules. | Prompt changes include version/hash expectations. | Prompt contract snapshot/semantic tests only where stable. | Medium |

## Single Source Of Truth Findings

| Concept | Existing locations | Problem | Canonical home | Merge / delete path | Acceptance criteria | Tests required | Confidence |
|---|---|---|---|---|---|---|---|
| Session status | Backend enum at `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:45`; DB check values at `backend/src/intric/database/tables/flow_tables.py:645`; frontend union at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:21`. | Status lifecycle must be updated in three places. | Backend enum/API schema, with DB constraint generated/kept in sync and frontend generated from OpenAPI. | Delete frontend union; add migration discipline for DB check. | Adding a status fails one contract test if not propagated. | OpenAPI/client generation test plus DB migration review checklist. | High |
| Plan status | Backend enum at `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:53`; DB check values at `backend/src/intric/database/tables/flow_tables.py:652`; frontend union at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:23`. | Same drift risk as session status. | Backend enum/API schema. | Delete frontend union. | Plan status required everywhere, no fallback default. | Contract tests. | High |
| Plan/spec/envelope | Backend Pydantic models at `backend/src/intric/flows/ai_builder/ai_builder_domain_models.py:228`; API response at `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:328`; frontend manual types at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:85`. | Frontend can drift from backend spec fields and optionality. | Backend API schema + generated TS. | Replace manual types. | Frontend plan pane compiles from generated types. | Typecheck and API contract tests. | High |
| SSE events | Backend constants/builders at `backend/src/intric/flows/ai_builder/ai_builder_events.py:22`; frontend manual event union at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:4`; driver switch at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:387`. | Streaming contract is manually synchronized. | Backend event models plus explicit frontend decoder. | Introduce versioned event decoder; remove raw casts. | Unknown event handled explicitly; event payload shape validated. | Frontend decoder unit tests. | Medium |
| Frontend AI Builder state | Driver state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45`; service state mirror at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:30`. | Two mutable owners. | One Svelte state store/service. | Make driver stateless transport or remove service mirror. | No field-by-field copy between owners. | State behavior tests. | High |
| Recoverable draft filtering | Driver filter at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:235`; service filter at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:132`. | Duplicate business rule. | Single frontend state owner or backend session-list query if this becomes API behavior. | Delete one filter immediately during state consolidation. | One function/test defines recoverability. | Frontend unit test. | High |
| Plan revision type | Backend literal at `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:241`; frontend literal at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:177`; service implementation at `backend/src/intric/flows/ai_builder/ai_builder_service.py:562`. | Type and behavior are split. | `AIBuilderPlanLifecycle` and generated API type. | Move service behavior; delete frontend manual literal. | Revision API, lifecycle, and frontend all derive from one contract. | API/lifecycle/frontend type tests. | High |
| AI Builder model aggregation | `ai_builder_models.py` re-exports API, domain, and event models at `backend/src/intric/flows/ai_builder/ai_builder_models.py:1`. | Compatibility aggregation hides ownership and encourages broad imports. | Concrete model modules. | Migrate imports to `ai_builder_domain_models`, `ai_builder_api_models`, or `ai_builder_event_models`; delete aggregation. | No production/test imports from `ai_builder_models.py`. | Import-linter or rg check. | High |

## Naming And Readability

| Finding | Evidence | Problem | Proposed fix | Confidence |
|---|---|---|---|---|
| Compatibility comments preserve test seams instead of naming deletion criteria. | Router compatibility seam at `backend/src/intric/flows/ai_builder/ai_builder_router.py:116`; router helper tuple at `backend/src/intric/flows/ai_builder/ai_builder_router.py:237`; planner compatibility comment at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1174`. | Comments explain why old tests/callers are preserved, but not owner/removal condition. | Convert to work items and delete in refactor; avoid indefinite comments. | High |
| Good intent comments exist around planning-state preservation. | `planning_state_builder.py` explains why persisted planner-owned fields must be carried forward at `backend/src/intric/flows/ai_builder/planning_state_builder.py:123`; planner explains prompt/state alignment at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1151`. | These are useful because deleting them would hide a non-obvious ordering invariant. | Keep until the lifecycle owner makes the invariant self-evident. | High |
| Generic names remain in hot paths. | `ProposalContext.llm_messages`, `tool_schemas`, `litellm_kwargs`, `assistant_metadata`, `process_tool_kwargs` at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:372`; frontend `protocol.ts` uses broad `Record<string, unknown>` for metadata/contracts at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:42`. | Some are boundary-appropriate, but many persist after parsing and become primitive bags. | Introduce typed command/value objects after the LLM/API boundary. | Medium |
| Restating comments in materializer steps are low value. | `execute_changeset` repeats numbered steps in comments and inline comments at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:208` and `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:230`. | These narrate code more than explaining invariants; the temp-flow ordering comment is the important one. | Replace with named phase functions or keep only ordering/recovery rationale. | Medium |

## Tests Touching AI Builder

| Test area | Evidence | Assessment | Proposed test posture | Confidence |
|---|---|---|---|---|
| Planning-state persistence integration | Session API regression tests cover save/load/CAS/commit paths; examples include save bump at `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:678`, stale base version at `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:720`, commit turn at `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:993`, rollback on drift at `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:1136`, and plan store state at `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:1715`. | Strong behavior coverage around the best-designed part of the system. | Preserve and use as guardrails for refactor. | High |
| Service tests | `test_ai_builder_service.py` creates broad `AsyncMock` repository fixtures at `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py:25`; delegation tests patch planner/lifecycle internals at `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py:823`. | Some tests assert implementation wiring rather than behavior, especially for pass-through service methods. | Delete/rewrite delegation tests after service responsibilities are clarified. | High |
| Apply/revision tests | Service tests cover unsupported revision type and stale revision paths at `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py:1613` and `backend/tests/unittests/flows/ai_builder/test_ai_builder_service.py:1682`. | Useful behavior coverage, but belongs to plan lifecycle once revision moves. | Move behavior expectations to lifecycle/API tests. | High |
| Frontend driver tests | Driver tests cover usage stream and refresh fallback at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts:444` and `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts:483`. | Valuable, but tied to current driver-as-state-owner design. | Preserve behavior while moving state owner; rewrite against service/store. | Medium |
| Test artifact hygiene | `wc -l` over test scope included checked-in `__pycache__` artifacts under `backend/tests/unittests/flows/ai_builder/__pycache__`. | Non-source artifacts distort inventories and should not be reviewed as tests. | Delete pyc files in cleanup phase; add ignore/check. | High |

## Highest-ROI Refactors

### 1. Make AI Builder Contracts Single-Source

| Required field | Assessment |
|---|---|
| Problem | Frontend manually duplicates backend statuses, session/plan/spec/envelope, revision, and event shapes. |
| Why it matters | Every backend contract change requires a manual frontend update and can silently drift. |
| Evidence | Backend plan response uses `PlannerPlanEnvelope` at `backend/src/intric/flows/ai_builder/ai_builder_api_models.py:328`; frontend duplicates plan/spec types at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:85`; frontend duplicates statuses at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:21`; frontend only uses generated `components` for telemetry at `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:238`. |
| Current owner | Backend API models plus frontend local protocol. |
| Proposed canonical home | Backend Pydantic API/event models; generated TypeScript client for HTTP; explicit typed SSE decoder for stream events. |
| Delete / merge path | Delete manual frontend HTTP schema/status/spec types after generated types cover them. |
| Acceptance criteria | `protocol.ts` contains only SSE stream adapter types and UI-only view models; session/plan/apply/revise types come from generated client. |
| Tests required | OpenAPI contract test; frontend typecheck; decoder tests for each SSE event. |
| Risk / trade-off | SSE may not be fully generated by OpenAPI; keep a narrow hand-written decoder for stream events. |
| Human reviewability impact | Very high. |
| Confidence | High. |

### 2. Split Proposal Processor By Real Domain Boundaries

| Required field | Assessment |
|---|---|
| Problem | The largest file owns too many independent lifecycle phases. |
| Why it matters | Create/edit proposal behavior is high-risk and currently hard to review safely. |
| Evidence | `AIBuilderProposalProcessor` evidence in hotspot section. |
| Current owner | `AIBuilderProposalProcessor`. |
| Proposed canonical home | Proposal transport/retry module; create proposal processor; edit proposal processor; plan persistence use case. |
| Delete / merge path | Replace `SubmissionToolHandlerConfig`/`ToolRetryConfig` callable-plus-dict dispatch with typed create/edit proposal commands. |
| Acceptance criteria | Create and edit proposal flows can be reviewed in separate files with typed inputs and behavior tests. |
| Tests required | Existing proposal processor tests split by create/edit/transport outcomes. |
| Risk / trade-off | Mechanical moves could be noisy; do behavior-preserving moves before behavior changes. |
| Human reviewability impact | Very high. |
| Confidence | High. |

### 3. Make Frontend State Ownership Singular

| Required field | Assessment |
|---|---|
| Problem | Driver and service both own/mirror AI Builder UI state. |
| Why it matters | Svelte reactivity depends on field copying and duplicated derived logic. |
| Evidence | Driver state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45`; service mirror at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:30`; service copies driver state at `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:266`. |
| Current owner | Split driver/service. |
| Proposed canonical home | `FlowAIBuilderService.svelte.ts` as state owner; driver as typed transport/event decoder. |
| Delete / merge path | Delete driver mutable state or delete service mirror; delete duplicate draft filters. |
| Acceptance criteria | One mutable state object; no forced reactive "touch" comments. |
| Tests required | State-store tests for stream events, phase transitions, apply conflict, draft recovery. |
| Risk / trade-off | Transport/event parsing should remain framework-independent. |
| Human reviewability impact | High. |
| Confidence | High. |

### 4. Turn Apply Into An Explicit Recoverable Lifecycle

| Required field | Assessment |
|---|---|
| Problem | Apply sets session status to `applying`, executes multiple flow/assistant mutations, then rolls back only if the process catches an exception. Edit-mode partial failure is more severe than create-mode cleanup because newly created/configured assistants can remain attached to an existing flow. |
| Why it matters | Process crash or partial mutation can leave a session stuck applying, orphan temp flow/assistants, or existing-flow assistant side effects that are not compensated. |
| Evidence | Status set to applying at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:133`; broad rollback at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:162`; rollback failure only logs at `backend/src/intric/flows/ai_builder/ai_builder_plan_lifecycle.py:315`; create mode creates a temporary flow at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:233`; edit/create execution creates assistants at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:266`, configures/updates assistants at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:273` and `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:281`, then updates the flow at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:320`; create-only cleanup depends on catching an exception at `backend/src/intric/flows/ai_builder/ai_builder_materializer.py:362`; `FlowService` exposes these as separate calls rather than a single AI Builder transaction at `backend/src/intric/flows/application/flow_service.py:154`, `backend/src/intric/flows/application/flow_service.py:222`, `backend/src/intric/flows/application/flow_service.py:264`, and `backend/src/intric/flows/application/flow_service.py:290`. |
| Current owner | `AIBuilderPlanLifecycle` and `ai_builder_materializer.py`. |
| Proposed canonical home | Plan lifecycle owns persisted apply attempt and recovery; materializer exposes idempotent mutation phases. |
| Delete / merge path | Replace catch-only rollback with explicit failed/recoverable states or reconciliation job. |
| Acceptance criteria | A crash after temp flow creation or edit-mode assistant creation has a deterministic recovery path; applying sessions can be retried/failed intentionally; edit-mode partial assistants are either transactional or reconciled. |
| Tests required | Crash simulation or integration tests around temp-flow cleanup, edit-mode partial assistant cleanup/reconciliation, stuck applying recovery, stale revision, retry idempotency. |
| Risk / trade-off | More state means migration and UI surface; worth it before shipping destructive apply behavior. Severity P0 for reliability. |
| Human reviewability impact | High for reliability. |
| Confidence | High. |

### 5. Delete Compatibility Aggregation And Test-Only Seams

| Required field | Assessment |
|---|---|
| Problem | Compatibility modules/helpers preserve old import/test paths and hide ownership. |
| Why it matters | They make future reviewers chase aliases and support behavior not meant for users. |
| Evidence | `ai_builder_models.py` re-exports three model modules at `backend/src/intric/flows/ai_builder/ai_builder_models.py:1`; router compatibility seam at `backend/src/intric/flows/ai_builder/ai_builder_router.py:116`; planner compatibility required-slot fallback at `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1174`. |
| Current owner | Compatibility layers. |
| Proposed canonical home | Concrete domain/API/event modules and public behavior tests. |
| Delete / merge path | Migrate imports/tests, delete aggregation/helper tuple/fallback. |
| Acceptance criteria | No production/test import from `ai_builder_models.py`; no private router helper tested directly. |
| Tests required | Import-linter/rg check plus public behavior tests. |
| Risk / trade-off | Import migration can be large; keep it mechanical and separate from behavior changes. |
| Human reviewability impact | Medium-high. |
| Confidence | High. |

## Non-Findings

| Area | Result |
|---|---|
| Planning-state JSONB discipline | No finding. The current persistence discipline is comparatively strong and should be preserved. |
| LLM repair loops as a category | No finding. LLM-boundary repair is necessary; the finding is about ownership, typed failure modes, and deleting non-LLM compatibility. |
| OpenAPI route metadata | No finding in sampled AI Builder routes. Operation IDs, summaries, response models, and response examples are present in `ai_builder_router.py`. |
| `_PRESERVED_PLAN_EDIT_TERMINAL_TYPES` | No finding. Claude suspected it might be dead, but local verification found it is used by `_terminal_output_type_from_prior_plan` at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:273`. |

## Claude Challenge Reconciliation

Claude iteration 1 returned `VERDICT: changes_required`, `GREEN_LIGHT: no`, minimum score 4, with artifact saved at `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260428T181739Z.md`.

Accepted changes:

| Claude challenge | Local verification | Reconciliation |
|---|---|
| Reframe the package as concentrated hotspot risk, not uniform sprawl. | Source inventory shows many narrow modules plus a few giant owners. | TL;DR and highest-ROI framing now focus on concentrated hotspots. |
| Apply-plan edit crash recovery is P0/P1, not just weak cleanup. | `execute_changeset` mutates assistants and flow via separate `FlowService` calls, with create-only catch cleanup. | Apply finding now explicitly covers edit-mode partial assistant side effects and calls for a transaction/ledger/reconciliation owner. |
| `ToolProcessingResult` is a success/failure bag. | Verified at `ai_builder_proposal_processor.py:295`. | Added typed-result finding and acceptance criteria. |
| Lease tokens are parameter pollution. | Verified repository CAS fields and repeated proposal signature threading. | Added lease context finding. |
| Router private helper seam is test-only. | Tests import `_get_space_models`, `_get_space_kbs`, and `_get_planner_model` directly at `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:34`. | Compatibility inventory already says delete; evidence sharpened. |
| `protocol.ts` duplication is backed by existing OpenAPI schema tests. | `REQUIRED_SCHEMAS` covers AI Builder API models at `backend/tests/unit/test_ai_builder_openapi_contract.py:27`. | Contract acceptance criteria now references generated schemas. |

Rejected or revised challenges:

| Claude challenge | Local verification | Decision |
|---|---|---|
| `_PRESERVED_PLAN_EDIT_TERMINAL_TYPES` might be dead. | It is referenced at `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:279`. | Rejected; documented as No finding. |
| Parallel create/edit scaffolding should be a major unifier via FCM. | Parallel modules are real, but the current evidence does not prove a safe single pipeline beyond shared final spec/materialization. | Kept as medium-confidence observation, not top-priority refactor. |
| Shared structured LLM repair abstraction should be extracted now. | Repair fragmentation is real, but premature extraction could create the kind of fake abstraction this review is meant to avoid. | Added as a watch item via proposal split; not a standalone acceptance criterion. |
| Lease tokens should be implicit in repo context. | DB CAS still needs explicit request/token identity; completely implicit context could hide write authorization. | Revised to "single typed active turn context" rather than hidden globals. |

Iteration 2 returned `VERDICT: green`, `GREEN_LIGHT: yes`, minimum score 7, with artifact saved at `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260428T182530Z.md`. The local wrapper exited nonzero because it did not parse Claude's bolded `GREEN_LIGHT: yes` line, but the review body explicitly green-lit the document and listed no blocking verification questions.

## Final Scorecard

| Dimension | Score | Rationale |
|---|---:|---|
| Maintainability | 4 | Strong local modules exist, but top-level planner/proposal/frontend state ownership is too broad. |
| Code Quality | 5 | Many typed Pydantic models and useful intent comments exist; large files, broad `Any`/dict bags, and compatibility paths reduce confidence. |
| Clean Architecture | 5 | Domain/persistence/API boundaries are visible, but router/service/materializer/planner responsibilities leak across layers. |
| Separation of Concerns | 4 | Proposal processor, planner, router, and frontend driver/service mix independent lifecycle phases. |
| Single Source of Truth | 3 | Backend/frontend contract duplication and duplicated state owners are active drift risks. |
| Human Readability | 4 | Important invariants are documented, but reviewers must read thousands of LOC to understand common changes. |
| Human Reviewability | 4 | Hotspot diffs are hard to approve safely because unrelated concerns live together. |
| Runtime Reliability | 5 | Send locks, leases, and planning-state CAS are good; apply crash recovery and partial materialization are weak. |
| Testability | 5 | Broad behavior coverage exists, but mock/delegation-heavy tests preserve current structure and pyc artifacts pollute inventories. |
| Overall | 3 | Minimum dimension score is 3: refactor required before further AI Builder feature work. |

## Executable Acceptance Criteria Summary

- [ ] Frontend AI Builder HTTP/session/plan/apply/revise types come from generated API types; `protocol.ts` keeps only SSE decoder and UI-only types.
- [ ] Exactly one frontend owner mutates AI Builder state; no field-by-field driver/service mirroring remains.
- [ ] Create and edit proposal processing are separated from LLM transport/retry and plan persistence.
- [ ] Proposal submission results use a discriminated success/failure type instead of `ToolProcessingResult` optional success/failure fields.
- [ ] Planner turn lock/lease/commit lifecycle can be reviewed without reading prompt assembly.
- [ ] Lease request/token pairs are not threaded through proposal helper signatures; a typed active-turn context owns write authorization.
- [ ] Plan revision behavior lives in `AIBuilderPlanLifecycle`, not in `AIBuilderService`.
- [ ] Apply has an explicit persisted recovery story for stuck `applying` sessions, temp-flow creation, and edit-mode assistant partial mutations.
- [ ] Test-only router compatibility helpers, planner compatibility fallback, `ai_builder_models.py` aggregation imports, frontend status fallback, and checked-in `__pycache__` artifacts are deleted in implementation phases.
- [ ] Refactor PRs separate mechanical moves from behavior changes and preserve existing planning-state integration tests.
