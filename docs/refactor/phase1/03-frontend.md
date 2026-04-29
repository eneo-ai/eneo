# Phase 1a Agent C - Frontend Architecture Review

1. TL;DR: Flow frontend architecture is below the refactor-required threshold because authoring state, run-launch state, evidence state, and AI Builder state have multiple owners.
2. TL;DR: The highest-leverage root cause is the manual flow type island in `resources.d.ts`, which duplicates generated OpenAPI schemas and forces downstream `Record<string, unknown>` parsing.
3. TL;DR: AI Builder has a literal Driver/Service state mirror; one of those classes must stop owning state before more feature work lands.
4. TL;DR: SvelteKit `load` functions are clean in the reviewed flow routes, but `+page.svelte` and large components compensate with route-level state, `$effect` synchronization, and prop-drilled command callbacks.
5. TL;DR: Tests cover pure helpers and driver internals, but the run dialog to runs table to evidence journey, editor state ownership, and AI Builder apply-to-flow path are not protected by component journey tests.

## Scope And Standards

Scope reviewed:

| Area | Evidence |
|---|---|
| Flow feature code | `frontend/apps/web/src/lib/features/flows/**` |
| Flow routes | `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/**` |
| Flow API client and types | `frontend/packages/intric-js/src/endpoints/flows.js`, `frontend/packages/intric-js/src/types/resources.d.ts`, `frontend/packages/intric-js/src/types/schema.d.ts` |
| Tests | Flow feature tests, `frontend/packages/intric-js/src/endpoints/flows.test.js`, and Phase 0 test baseline |

Standards applied:

| Standard | Relevant rule |
|---|---|
| `docs/engineering/maintainability-standards.md` | One canonical owner, delete or merge before adding, typed boundaries over primitive bags. |
| `docs/engineering/frontend-state-standard.md` | One owner per piece of UI state; flag Driver/Service/component duplication, `$effect` synchronization, manual backend types, `any` and `unknown`. |
| `docs/engineering/api-design-standard.md` | Generated client quality and explicit API contract ownership matter for maintainability. |
| `docs/engineering/testing-standard.md` | Frontend tests should protect behavior and critical journeys, not private helper calls. |
| `docs/engineering/comment-and-readability-standard.md` | Comments and names should explain intent, not preserve unclear design. |

No source, test, migration, dependency, generated client, or git changes were made. This document is the only intended output.

## Findings By Severity

| ID | Severity | Finding | Canonical home | Confidence |
|---|---:|---|---|---|
| F1 | P1 | Flow API/resource contracts have a manual type island while generated schemas already exist. | Generated OpenAPI schema in `schema.d.ts`, with narrow aliases in `resources.d.ts`. | High |
| F2 | P1 | AI Builder state is mirrored between Driver and Service. | One AI Builder session controller; delete or demote the other layer. | High |
| F3 | P1 | Flow authoring state is split across route, `FlowEditor`, edit panel, form schema editor, and AI Builder callbacks. | Deepen `FlowEditor` into the single authoring session owner. | High |
| F4 | P2 | Run-launch workflow is embedded in `FlowRunDialog.svelte`. | A typed `FlowRunLaunchSession` plus existing pure contract/wizard helpers. | High |
| F5 | P2 | Evidence, progress, and status rendering duplicate parsing and status presentation with broad records. | Generated evidence/run types plus one status presentation primitive. | High |
| F6 | P2 | Component journey tests are missing for the critical run and evidence workflows. | Frontend component tests and one flow E2E journey. | High |
| F7 | P2 | Store-based and rune-based state paradigms coexist without a declared rule. | Frontend flow state standard section or ADR. | Medium |
| F8 | P3 | Legacy/compatibility paths remain in pre-production frontend code. | Phase 1b dead-code inventory or the owning refactor PRD. | Medium |

## Driver Vs Service Vs Component State Ownership

### Current Ownership Inventory

| Concept | Current locations | Problem | Canonical home | Merge/delete path |
|---|---|---|---|---|
| Flow authoring resource and autosave | `FlowEditor.ts:27-46`, `FlowEditor.ts:344-396` | `FlowEditor` owns update/autosave but the route and panels still mutate state around it. | `FlowEditor` as the authoring session owner. Rename only if it becomes broader than editor state. | Move route-level and panel-level domain mutations into typed `FlowEditor` commands; delete direct step mutation callbacks. |
| Active step and validation state | `FlowEditor.ts:91-99`, `FlowEditor.ts:146-155`, `[flowId]/+page.svelte:41-57`, `FlowStepEditPanel.svelte:223-251` | Validation and active step concerns are partly in editor stores, route state, and panel effects. | `FlowEditor` owns active step, validation, publish readiness, and step JSON draft lifecycle. | Keep panel-local drafts only where they are unsaved UI text; route reads derived values. |
| Step mutation and ordering | `FlowEditor.ts:398-449`, `FlowEditor.ts:451-518`, `FlowEditor.ts:591-681`, `[flowId]/+page.svelte:901-948`, `FlowStepEditPanel.svelte:285-333` | Route and panel can mutate step arrays while `FlowEditor` also owns safe ordering and reference rewrites. | `FlowEditor` command API: add, insert, update, remove, reorder, remap references. | Delete route-level `$update.steps[index] = step` mutation and stringly `updateStep(field, value)` callback surface. |
| Flow metadata/form schema | `[flowId]/+page.svelte:117-177`, `[flowId]/+page.svelte:226-240`, `FlowFormSchemaEditor.svelte:52-89`, `flowFormSchema.ts:1-137` | Metadata and form schema are parsed and rewritten from multiple components. | A typed metadata/form-schema model owned by `FlowEditor`, using `flowFormSchema.ts` for parsing/normalization. | Route should not mutate `metadata_json`; form editor emits typed schema commands. |
| AI Builder session state | `FlowAIBuilderDriver.ts:45-60`, `FlowAIBuilderDriver.ts:96-125`, `FlowAIBuilderService.svelte.ts:26-43`, `FlowAIBuilderService.svelte.ts:266-280` | Service copies every driver field into `$state`, creating two state sources. | One AI Builder session controller. Recommended: Service owns Svelte reactivity and workflow state; Driver becomes stateless transport/parser or is deleted. | Remove `#applyState` mirror. Move hard-coded paths and SSE parsing behind a typed client adapter. |
| AI Builder phase | `FlowAIBuilderDriver.ts:649-659`, `FlowAIBuilderService.svelte.ts:147-155`, `FlowAIBuilder.svelte:21-70` | Phase derivation lives in Driver, but Service uses reactive no-op touches to expose it. | Same AI Builder controller that owns session state. | Replace `void this.#messages` style reactivity with explicit derived state in the chosen owner. |
| Run-launch wizard state | `FlowRunDialog.svelte:71-214`, `flowRunContract.ts:40-69`, `flowRunWizard.ts:78-294` | Pure helpers exist, but the dialog still owns contract loading, runtime files, recording, wizard pages, blockers, idempotency, and submit. | `FlowRunLaunchSession` or equivalent flow-run launch module. | Keep helpers; move mutable workflow state and commands out of the component. |
| Run history and latest payload | `FlowRunsTable.svelte:24-54`, `FlowRunsTable.svelte:115-209`, `[flowId]/+page.svelte:1150-1174` | Route binds latest run payload and highlight state into table, while table owns polling and history fetches. | `FlowRunHistorySession` or table-local state with a narrow event contract. | Prefer table/session owns history state; route receives `runCreated` events only. |
| Evidence payload and grouping | `FlowRunEvidence.svelte:45-85`, `FlowRunEvidence.svelte:167-180`, `FlowRunEvidenceStepCard.svelte:56-86` | Evidence component re-declares payload as records despite generated evidence schemas. | Generated `FlowRunEvidenceResponse` and typed view model owned by evidence module. | Delete local `EvidencePayload` record type and callback-prop status plumbing. |

### F1 - Manual Flow Type Island Blocks Typed Frontend Ownership

Problem: Flow frontend contracts are manually maintained in `resources.d.ts` even though generated OpenAPI schemas already include the relevant flow models.

Why it matters: Every state owner decision becomes weaker when the data contract is duplicated. Components and drivers cast around missing generated types, which makes invalid state easier to hide and harder to review.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/packages/intric-js/src/types/resources.d.ts:153-172` | Flow types are introduced as manual definitions "until OpenAPI schema is generated"; `FlowStep` uses broad `Record<string, unknown>` configs. |
| `frontend/packages/intric-js/src/types/resources.d.ts:241-276` | Run contract types are manual. |
| `frontend/packages/intric-js/src/types/resources.d.ts:295-313` | Flow run status and run payload types are manual. |
| `frontend/packages/intric-js/src/types/resources.d.ts:490-520` | Evidence/debug export types are manual and broad. |
| `frontend/packages/intric-js/src/types/schema.d.ts:11844-11860` | Generated `FlowRunContractPublic` already exists. |
| `frontend/packages/intric-js/src/types/schema.d.ts:12811-12821` | Generated `FlowRunEvidenceResponse` already exists. |
| `frontend/packages/intric-js/src/types/schema.d.ts:16428-16431` | Generated `PlannerPlanEnvelope` already exists. |
| `frontend/packages/intric-js/src/types/schema.d.ts:17348-17370` | Generated `SessionStatus` already exists. |
| `frontend/packages/intric-js/src/types/schema.d.ts:17872-17875` | Generated `StepSpec` already exists. |
| `frontend/packages/intric-js/src/types/schema.d.ts:18121-18124` | Generated `TargetKind` already exists. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:19-23` | AI Builder redefines target and status strings manually. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:85-105` | AI Builder redefines `StepSpec` using `Record<string, unknown>`. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:127-169` | AI Builder redefines plan envelope structures. |

Current owner: `frontend/packages/intric-js/src/types/resources.d.ts` is acting as the manual public type owner, while `schema.d.ts` is the generated contract owner.

Proposed canonical home: `frontend/packages/intric-js/src/types/schema.d.ts` generated from backend OpenAPI. `resources.d.ts` may keep stable resource aliases only when they directly reference `components["schemas"]`.

What to delete or merge: Delete the manual flow block in `resources.d.ts:153-530` once generated aliases are in place. Delete duplicate AI Builder protocol model definitions that match generated schemas. Keep only UI-only view models that do not exist in the backend contract.

Acceptance criteria:

- `resources.d.ts` no longer says flow types are manual until OpenAPI schema generation.
- `Flow`, `FlowStep`, `FlowRun`, `FlowRunContract`, `FlowRunEvidence`, AI Builder session/status/plan/step types are generated aliases or explicitly documented UI-only types.
- `FlowRunDialog.svelte`, `FlowRunEvidence.svelte`, and AI Builder no longer need public boundary props typed as `Record<string, unknown>` for generated API payloads.
- `frontend/packages/intric-js/src/endpoints/flows.js:440` no longer deletes a required `flow_id` field from a typed object.

Tests required:

- API client contract tests for run create, contract fetch, evidence fetch, and AI Builder session/plan operations using generated request and response types.
- Typecheck should catch drift between OpenAPI schema and frontend flow client usage.

Risk/trade-off: This may expose backend OpenAPI schema gaps. If generated schemas are incomplete, fix schema ownership instead of adding a second handwritten frontend schema.

Human reviewability impact: High positive. Reviewers can inspect one generated type source instead of reconciling schema, `resources.d.ts`, `protocol.ts`, and component-local records.

Confidence: High.

### F2 - AI Builder Service Mirrors Driver State

Problem: `FlowAIBuilderService.svelte.ts` declares its own `$state` fields and then copies the entire `FlowAIBuilderDriver` state into them on every driver change.

Why it matters: Adding one logical AI Builder state field currently implies changes across protocol types, Driver state, Service state, and consuming components. That is a parallel implementation, not a stable layer boundary.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:26-43` | Service declares mirrored `$state` fields for session, messages, plan, streaming state, errors, models, drafts, and summaries. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:63-69` | Service casts `intric.client` through `unknown` to a local `AIBuilderClientTransport`. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:147-155` | `phase` getter uses reactive no-op touches and delegates derivation to Driver. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:173-260` | Public Service methods are mostly pass-through calls to Driver. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts:266-280` | `#applyState` copies every Driver state field into Service state. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:45-60` | Driver defines its own full `FlowAIBuilderState`. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:306-479` | Driver owns SSE event parsing and state mutation. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:649-659` | Driver derives phase from plan/session/streaming state. |

Current owner: Both `FlowAIBuilderDriver` and `FlowAIBuilderService.svelte.ts`.

Proposed canonical home: One AI Builder session controller. The lower-risk path for Svelte 5 is to let `FlowAIBuilderService.svelte.ts` own reactive UI state and workflow commands, while converting `FlowAIBuilderDriver.ts` into a stateless typed transport/SSE parser plus pure reducers. If the team prefers a non-rune controller, delete the Service shell and expose a small reactive adapter around Driver. Do not keep both as state owners.

What to delete or merge:

- Delete `#applyState` field-by-field mirroring.
- Delete pass-through methods that only rename Driver methods.
- Move hard-coded paths in `FlowAIBuilderDriver.ts:181-211` and `FlowAIBuilderDriver.ts:503-550` into the generated client or a narrow typed client adapter.
- Replace manual protocol types with generated schema aliases where possible.

Acceptance criteria:

- There is one mutable AI Builder state object.
- Phase derivation lives in the same owner as the state it derives from.
- Components no longer need to understand Driver versus Service responsibilities.
- AI Builder client transport has typed request and response contracts.

Tests required:

- Component test for draft auto-resume still passing through `FlowAIBuilder.svelte`.
- Session-controller test for create, refresh, stream message, structured question handling, apply plan conflict, and abort.
- API transport contract test for generated client paths and response typing.

Risk/trade-off: Deleting the wrong layer may create a large diff. The first PR should choose the target owner and remove one mirroring seam without redesigning the whole builder UI.

Human reviewability impact: High positive. Reviewers should see one state transition path for create, stream, plan, apply, and error handling.

Confidence: High on the duplication; medium on which class should survive.

### F3 - Flow Authoring State Has No Single Owner

Problem: The route, `FlowEditor`, `FlowStepEditPanel`, `FlowFormSchemaEditor`, and AI Builder apply callback all mutate or derive authoring state.

Why it matters: A reviewer must reconstruct flow authoring behavior from stores, route `$state`, component effects, callback props, and direct resource mutation. That makes publish readiness, step references, metadata, and autosave harder to evolve safely.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:27-46` | `FlowEditor` initializes resource editing and owns update calls. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:91-99` | `FlowEditor` owns active step, validation, save status, and publish state stores. |
| `frontend/apps/web/src/lib/features/flows/FlowEditor.ts:344-396` | `FlowEditor` owns debounced autosave and validation subscriptions. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:41-57` | Route owns publish loading, dialog state, run reload/highlight state, step JSON validation state, and builder stage. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:141-177` | Route syncs transcription model state from `metadata_json`. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:226-240` | Route mutates wizard metadata directly. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:272-333` | Route publishes/unpublishes through direct API calls and resource mutation. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:901-930` | Route receives edited steps and directly mutates `$update.steps[index]`. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:1108-1140` | Route applies AI Builder result, fetches a fresh flow, updates editor resource, moves tab/stage/focus. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:285-333` | Edit panel exposes `updateStep(field: string, value: unknown)` and mutates assistant-related fields. |
| `frontend/apps/web/src/lib/features/flows/components/FlowFormSchemaEditor.svelte:52-89` | Form schema editor parses and writes `metadata_json.form_schema` directly. |

Current owner: Split between route orchestration, `FlowEditor`, and edit components.

Proposed canonical home: Deepen `FlowEditor` into the single flow authoring session owner. Keep the existing name for Phase 1 to avoid mixing behavior movement with a cross-file rename. It should own authoring resource state, active step, validation, publish readiness, form schema metadata, step mutations, assistant/template subcontrollers, and post-AI-builder apply refresh.

What to delete or merge:

- Delete route-level direct step array mutation and direct metadata mutation.
- Replace `updateStep(field: string, value: unknown)` with typed authoring commands.
- Move publish/unpublish command state behind the authoring session, or explicitly keep the route as a thin command adapter that does not own domain state.
- Move transcription model sync out of route `$effect` into typed metadata commands.

Acceptance criteria:

- The route page reads authoring state and invokes commands; it does not mutate flow steps or metadata directly.
- `FlowStepEditPanel` emits typed intent commands or receives a typed command object.
- Form schema is parsed, normalized, and written in one place.
- AI Builder apply returns through one authoring-session refresh path.

Tests required:

- Component or integration test for edit step -> autosave -> validation banner.
- Test for reorder/delete with reference remapping and publish readiness.
- Test for form schema update writing canonical metadata shape.
- Test for AI Builder apply updating flow, focusing the expected step, and leaving the route in a stable state.

Risk/trade-off: A single large rewrite would be hard to review. Slice by command boundary: first stop direct route mutations, then move metadata, then normalize panel commands.

Human reviewability impact: High positive. Entry points become obvious: route shell, authoring session, panels as views.

Confidence: High.

## SvelteKit State Audit

### Load Side Effects

No findings.

Evidence:

| Route | Evidence | Assessment |
|---|---|---|
| Flow list | `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/+page.ts:4-19` | Loads parent data, checks permission, fetches flows. No observed mutation outside data loading. |
| Flow editor | `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.ts:4-19` | Disables SSR, checks permission, fetches flow, validates space. No observed mutation outside data loading. |

### Route And Context State

Problem: Route components initialize service contexts and hold domain state that child components also affect.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/+page.svelte:23-33` | Flow list route initializes `FlowsManager` using `untrack`. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:67-72` | Editor route initializes `FlowUserMode` and `FlowEditor`. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:74-80` | Editor route lazily tracks AI Builder initialization. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:104-115` | Route effects destroy editor and force active tab based on permission. |
| `frontend/apps/web/src/lib/features/flows/FlowUserMode.ts:19-37` | User mode context subscribes to local storage; lifecycle ownership is not obvious at the call site. |

Canonical home: Route components should own URL, permission, layout shell, and lifecycle cleanup. Domain state belongs in the flow authoring session, AI Builder session, run launch/history sessions, or typed child-local UI state.

Acceptance criteria:

- Route state list is limited to URL/tab/dialog shell state and command wiring.
- Context constructors document whether they are route-scoped and how they are destroyed.
- `FlowUserMode` has an explicit lifecycle contract or a store implementation that cannot leak subscriptions.

Tests required:

- Route/component lifecycle test for context initialization and destroy where feasible.
- Unit test for user mode persistence behavior.

Risk/trade-off: Some Svelte context setup must remain in route/page components. The refactor should target domain state, not all state.

Human reviewability impact: Medium positive.

Confidence: Medium.

### `$effect` Synchronization

Problem: Several `$effect` blocks synchronize state because ownership is unclear.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:141-177` | Route synchronizes local transcription model fields from metadata. |
| `frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/[flowId]/+page.svelte:202-208` | Route auto-selects a first step when entering an AI Builder stage. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:223-251` | Panel synchronizes advanced JSON drafts and errors from active step changes. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:269-279` | Panel synchronizes assistant state and attachment rules. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:270-323` | Dialog effects load contract on open and reset mutable workflow state on close. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunsTable.svelte:170-209` | Table effects load runs and poll active runs. |

Assessment: Not every `$effect` is wrong. Loading on dialog open and polling active runs can be legitimate UI lifecycle effects. The misuse is where effects translate one domain state into another long-lived domain state, especially route metadata sync and panel draft sync.

Canonical home: Domain derivations should be getters/selectors on the state owner. Effects should remain for lifecycle edges: open/close, subscribe/unsubscribe, timer start/stop, visibility, and imperative browser APIs.

Acceptance criteria:

- Metadata-derived fields are derived or commanded from the authoring session, not copied in route effects.
- Advanced JSON drafts are clearly panel-local unsaved text, not a second source for persisted step config.
- Polling and dialog-open effects have cleanup and idempotency tests.

Tests required:

- Metadata/form schema derivation test.
- Dialog open/close reset test.
- Runs table polling cleanup test.

Risk/trade-off: Svelte effects are normal for UI lifecycle. The target is not zero effects; the target is no effect-based domain ownership.

Human reviewability impact: Medium positive.

Confidence: High.

## Component Review

### Large Responsibility Inventory

| File | Approx. LOC from Phase 0 | Current responsibility | Recommendation |
|---|---:|---|---|
| `FlowRunDialog.svelte` | 1196 | Contract load, form state, runtime files, recording, wizard, submit, close confirmation. | Extract run-launch session first; then split views by wizard page only if still useful. |
| `[flowId]/+page.svelte` | 1185 | Route shell, authoring orchestration, publish, AI Builder tab/stage, run dialog/history wiring. | Reduce to URL/layout/permission shell plus session wiring. |
| `FlowStepEditPanel.svelte` | 1157 | Step field editing, assistant state, JSON drafts, transition policy, template fill, attachments. | Replace stringly update callbacks with typed authoring commands; keep view-local drafts. |
| `FlowAIBuilderDriver.ts` | 992 | API calls, SSE parsing, state machine, phase derivation, drafts, summaries. | Choose Driver or Service as owner; remove mirror. |
| `FlowEditor.ts` | 825 | Authoring resource, autosave, validation, assistant save manager, step operations, reference remap. | Deepen as canonical authoring session; remove external direct mutations. |
| `FlowRunsTable.svelte` | 727 | History load, polling, filtering/sorting, redispatch/cancel, progress/evidence switching. | Extract run-history session or keep table owner with narrow events. |
| `FlowRunEvidence.svelte` plus `FlowRunEvidenceStepCard.svelte` | Component pair | Evidence fetch, grouping, status presentation, output/payload parsing. | Use generated evidence types and one status primitive. |

### F4 - Run Launch Workflow Lives In The Dialog Component

Problem: `FlowRunDialog.svelte` is both a view and the run launch application workflow.

Why it matters: The launch path has file uploads, audio recording, step input mapping, dirty-close protection, idempotency, and run creation. Keeping that in one Svelte component makes it hard to test without rendering every visual branch.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:55-69` | Public props include `lastInputPayload: Record<string, unknown> | null`. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:71-90` | Dialog owns form values, runtime files, recording, uploading, wizard page, errors, dirty confirmation, and element refs. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:96-323` | Dialog derives required fields, runtime steps, pages, blockers, review summary, submit capability, open loading, and close reset behavior. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:510-613` | Dialog owns runtime file upload behavior, size/count validation, and upload errors. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:624-722` | Dialog owns recording lifecycle and upload retry behavior. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:794-858` | Dialog builds payloads, creates idempotency key, submits run, resets state, and emits run-created. |
| `frontend/apps/web/src/lib/features/flows/flowRunContract.ts:40-69` | Existing pure helpers already own step input payload and run intent building. |
| `frontend/apps/web/src/lib/features/flows/flowRunWizard.ts:78-294` | Existing pure helpers already own wizard pages, blockers, and review summary. |

Current owner: `FlowRunDialog.svelte`, with partial pure helper ownership.

Proposed canonical home: `FlowRunLaunchSession` owns mutable launch state and commands. Existing `flowRunContract.ts` and `flowRunWizard.ts` remain pure helpers. Dialog components render session state and dispatch commands.

What to delete or merge:

- Move contract load, form value state, runtime file state, recording state, dirty-close state, and submit command out of the dialog.
- Replace `lastInputPayload: Record<string, unknown>` with a generated run input payload type.
- Keep page-specific components such as form/runtime/review views, but make them dumb views.

Acceptance criteria:

- `FlowRunDialog.svelte` does not call the API client directly except through the launch session.
- Upload, recording, wizard, and submit behavior are testable without asserting internal component helpers.
- The dirty-close and reset rules are documented by behavior tests.

Tests required:

- Component journey: open dialog, load contract, fill form fields, upload or record runtime input, submit, assert `onRunCreated`.
- Error journey: upload failure and create-run failure preserve recoverable state.
- Dirty-close journey: close confirmation appears only when unsaved launch state exists.

Risk/trade-off: A launch session adds a new file. It earns its existence because there is a real application workflow with browser APIs, API calls, idempotency, and several view components.

Human reviewability impact: High positive.

Confidence: High.

### F5 - Evidence And Status Rendering Rebuild Typed Contracts Locally

Problem: Evidence and status components parse records and pass status presentation callbacks instead of using generated run/evidence contracts and a reusable status primitive.

Why it matters: Evidence is a debugging and provenance surface. Broad records make it easy to display stale or misinterpreted runtime state, and duplicated status handling makes future lifecycle states drift.

Evidence:

| Evidence | Detail |
|---|---|
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:45-51` | Local `EvidencePayload` uses `Record<string, unknown>` for run, definition, and attempts. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:77-85` | Component fetches evidence directly. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:112-128` | Component wraps status presentation locally. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:167-180` | Component groups attempts by numeric fields from unknown records. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:219-229` | Component parses transcription from `input_payload_json` as a record. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidenceStepCard.svelte:56-86` | Step card accepts records and status callback props. |
| `frontend/apps/web/src/lib/features/flows/flowRunProgress.ts:40-49` | Active and terminal statuses are hard-coded string lists. |
| `frontend/apps/web/src/lib/features/flows/flowRunStatusLabel.ts:1-18` | Status labels are string switches. |
| `frontend/apps/web/src/lib/features/flows/flowRunStatusPresentation.ts:3-34` | Status visual presentation is another string switch. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunStatusBadge.svelte:9-15` | Badge prop is `string`, with statuses documented in a comment. |
| `frontend/packages/intric-js/src/types/schema.d.ts:12811-12821` | Generated evidence response type exists. |

Current owner: Local evidence components and status helper files.

Proposed canonical home: Generated evidence/run types define payload shape. `FlowRunStatusBadge` and `flowRunStatusPresentation.ts` become the single status presentation primitive, typed by generated run status.

What to delete or merge:

- Delete local `EvidencePayload` broad-record type.
- Delete status callback props from `FlowRunEvidenceStepCard`.
- Merge status string lists and presentation switches behind one typed status module.

Acceptance criteria:

- Evidence fetch returns `FlowRunEvidenceResponse` or a typed view model derived from it.
- Status helpers consume a generated status union or a central local alias with a documented backend source.
- Step card receives typed attempts, typed step definitions, and renders status through `FlowRunStatusBadge` or the central primitive.

Tests required:

- Evidence render test with a typed fixture covering completed, failed, running, missing output, and transcription payload.
- Status presentation test using the generated status union and an unknown/future-state fallback rule if the backend contract allows it.

Risk/trade-off: Generated evidence schemas may expose optionality that the component currently hides. That should be handled with explicit empty states, not broad casts.

Human reviewability impact: High positive.

Confidence: High.

### Component Findings With No Additional Issues

| Component | Result |
|---|---|
| `FlowRunDialogForm.svelte` | No standalone architecture finding beyond parent dialog ownership. |
| `FlowRunDialogRuntimeStep.svelte` | No standalone architecture finding beyond parent launch workflow ownership. |
| `FlowRunDialogReview.svelte` | No standalone architecture finding beyond parent launch workflow ownership. |
| `FlowAIBuilderPhaseIndicator.svelte` | No standalone architecture finding; issue is phase ownership in AI Builder controller. |

## Reusable Primitive Inventory

| Concept | Existing primitive | Gap | Canonical home |
|---|---|---|---|
| Run status pill | `FlowRunStatusBadge.svelte`, `flowRunStatusPresentation.ts`, `flowRunStatusLabel.ts` | Untyped `string` status and duplicated active/terminal lists. | One typed status module plus badge component. |
| Run wizard pages/blockers | `flowRunWizard.ts` | Mutable wizard state still lives in dialog. | `flowRunWizard.ts` remains pure; launch session owns state. |
| Run intent/payload building | `flowRunContract.ts` | Public component props and client requests are not generated-typed. | Generated run contract types plus `flowRunContract.ts`. |
| Evidence viewer | `FlowRunEvidence.svelte`, `FlowRunEvidenceStepCard.svelte` | Local record parsing and status callback props. | Typed evidence view model module. |
| Flow form schema | `flowFormSchema.ts`, `FlowFormSchemaEditor.svelte` | Metadata ownership is split between route/editor/component. | Flow authoring session owns metadata; helper remains parser/normalizer. |
| Step status pill | No clear reusable primitive in reviewed flow frontend. | Step run output statuses are typed manually and rendered ad hoc in evidence/progress surfaces. | Typed step status primitive aligned with generated step output status. |
| File upload/recording input | Embedded in `FlowRunDialog.svelte` | Browser API and upload state cannot be reused or tested cleanly. | Run launch session plus small view components. |
| Error/loading/empty states | Local component markup. | No flow-specific reusable primitive; acceptable until duplication becomes visible. | No new abstraction now unless repeated screens converge. |

## Type Safety Audit

| Location | Issue | Why it matters | Canonical fix |
|---|---|---|---|
| `frontend/packages/intric-js/src/types/resources.d.ts:153-530` | Manual flow resource definitions. | Duplicates generated schema and freezes stale TODO into the public type package. | Generated aliases from `schema.d.ts`. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:19-185` | Manual statuses, session, plan, step, and apply result definitions. | Duplicates generated AI Builder schemas and broadens configs to records. | Generated schemas plus UI-only local view models. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:35-43` | Local transport uses `unknown` init/results. | Hard-coded API paths are not checked against OpenAPI. | Generated client operation types or typed adapter. |
| `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:306-479` | Manual SSE `JSON.parse` and event type narrowing. | Event schema drift becomes runtime-only failure. | Typed stream event union and parser at API boundary. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunDialog.svelte:55-69` | `lastInputPayload` public prop is `Record<string, unknown>`. | Parent/table/dialog can disagree on shape. | Generated run input payload type. |
| `frontend/apps/web/src/lib/features/flows/components/FlowRunEvidence.svelte:45-51` | Evidence payload rebuilt as records. | Loses generated evidence contract. | Generated `FlowRunEvidenceResponse`. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepEditPanel.svelte:285-333` | `updateStep(field: string, value: unknown)`. | Invalid fields and values can pass through component boundaries. | Typed step command methods. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepBehaviorSection.svelte:41-58` | Props include `assistant: any`, `availableModels: any[]`, `formSchema: any`, `stepUxCopy: any`. | Child component API is unreviewable and can drift from editor owner. | Typed props from generated flow/assistant/model schemas and flow form schema. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepContextSection.svelte:23-37` | Props include `assistant: any` and several `any[]` collections. | Context selection can accept invalid resource shapes. | Typed assistant and knowledge resource props. |
| `frontend/apps/web/src/lib/features/flows/components/FlowStepInputTemplateSection.svelte:34-55` | Props include `formSchema: any` and `stepUxCopy: any`. | Template fill rules depend on untyped schema. | `FlowFormSchema` and typed UX copy model. |

No `@ts-ignore` finding was identified in the scoped evidence collected for this document.

## API Client Review

### Current API Client Boundary

| Location | Evidence | Finding |
|---|---|---|
| `frontend/packages/intric-js/package.json:8-20` | Package has an `update` script and `openapi-typescript`. | Generated API typing is already part of the package workflow. |
| `frontend/packages/intric-js/update.js:3-14`, `frontend/packages/intric-js/update.js:41` | Script fetches `/openapi.json` and generates `src/types/schema.d.ts`. | Flow types should use the same generation path as other resources. |
| `frontend/packages/intric-js/README.md:62` | Package documents backend types as autogenerated from `openapi.json`. | Manual flow types violate package-level expectation. |
| `frontend/packages/intric-js/src/endpoints/flows.js:6-8` | `_fetch` casts client to `any`. | Endpoint implementation bypasses typed request/response shape. |
| `frontend/packages/intric-js/src/endpoints/flows.js:11-30` | Stable sort helper accepts `any` and returns `Record<string, any>`. | Idempotency key generation is not typed to run intent. |
| `frontend/packages/intric-js/src/endpoints/flows.js:63-77`, `frontend/packages/intric-js/src/endpoints/flows.js:97-105` | Run intent and idempotency params use `any`. | Run creation boundary is weakly typed. |
| `frontend/packages/intric-js/src/endpoints/flows.js:136-153` | Create/update flow accepts `steps?: any[]` and `metadata_json?: any`. | Authoring API can submit invalid step/metadata shapes. |
| `frontend/packages/intric-js/src/endpoints/flows.js:412-447` | Run create normalizes then deletes `flow_id`. | Phase 0 already recorded a typecheck diagnostic at line 440. |
| `frontend/packages/intric-js/src/endpoints/flows.test.js:5-180` | Tests assert routes, payloads, and idempotency behavior. | Useful client behavior coverage exists, but not generated contract coverage. |

### API Client Finding

Problem: The flow endpoint module has useful behavior tests, but its JSDoc/types are not backed by generated operation contracts.

Why it matters: API consumers rely on `intric-js` as the stable frontend/backend boundary. If flow endpoints use `any` and manual resource types, maintainers cannot trust TypeScript to catch contract drift.

Current owner: `frontend/packages/intric-js/src/endpoints/flows.js` plus manual `resources.d.ts`.

Proposed canonical home: Generated OpenAPI operation types and schema aliases, with `flows.js` as a thin JavaScript endpoint adapter.

What to delete or merge:

- Delete `any` endpoint request/response JSDoc where generated operation types exist.
- Replace manual run intent normalization types with generated request-body aliases and a typed idempotency input type.
- Fix the `delete normalizedRequest.flow_id` issue by separating route path params from request body type.

Acceptance criteria:

- Flow endpoint functions expose generated response/resource types.
- Route path parameters are not mixed into body objects and then deleted.
- Endpoint tests still verify URL, method, body, and headers, but typechecking verifies request/response shape.

Tests required:

- Existing endpoint tests remain.
- Add type-level or compile-time coverage for run create and evidence response shapes if the package supports that pattern.

Risk/trade-off: JavaScript endpoint files can still use JSDoc. The goal is not a TypeScript rewrite; it is one canonical generated contract.

Human reviewability impact: High positive.

Confidence: High.

## Frontend Test Quality

### Current Test Inventory

| Area | Evidence | Assessment |
|---|---|---|
| Pure run helpers | `frontend/apps/web/src/lib/features/flows/flowRunContract.test.ts:10-62`, `frontend/apps/web/src/lib/features/flows/flowRunWizard.test.ts:10-214` | Good behavior coverage for payload normalization, template readiness, wizard pages, blockers, and review summaries. |
| AI Builder driver | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.test.ts:52-220` | Strong internal driver coverage, but tied to current Driver as implementation owner. |
| AI Builder component | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilder.test.ts:1-60` | Some component coverage through a harness, mainly auto-resume. |
| API endpoint adapter | `frontend/packages/intric-js/src/endpoints/flows.test.js:5-180` | Covers routes, payloads, and idempotency behavior. |
| Phase 0 frontend unit baseline | `docs/refactor/phase0/baseline.md` | Vitest collected 460 passing tests before unhandled missing `jsdom` environment failures. |
| Flow component journeys | Search of flow test files | No dedicated component journey tests found for `FlowRunDialog`, `FlowRunsTable`, `FlowRunEvidence`, `FlowEditor`, or the flow editor route as systems under test. |
| Flow E2E | Search excluding `node_modules` | No flow Playwright spec found in the reviewed repository tree. |

### F6 - Critical Component Journeys Are Unverified

Problem: Tests cover pure helpers and driver internals, but not the workflows that users exercise through Svelte components.

Why it matters: The riskiest frontend behavior is stateful and cross-component: launch a run, upload runtime files or recordings, submit with idempotency, refresh the history row, open evidence, and inspect progress. Typecheck and pure helper tests cannot prove that workflow.

Current owner: No clear test owner for flow component journeys.

Proposed canonical home: Frontend component tests under the flow feature for view/session behavior, plus one Playwright critical path when backend fixtures can support it.

Acceptance criteria:

- `FlowRunDialog` has a component journey test covering contract load, form fill, runtime input upload or recording substitute, submit, and `onRunCreated`.
- `FlowRunsTable` has a test for active polling, cancel/redispatch command availability, and evidence/progress rendering switch.
- `FlowRunEvidence` has a typed fixture render test for successful, failed, and partial step outputs.
- Flow editor/authoring session has a test for step mutation and publish readiness that does not assert private helper calls.
- AI Builder apply-to-flow has a test proving apply refreshes the flow and focuses the expected step.

Tests required: Same as acceptance criteria.

Risk/trade-off: Component tests need stable fakes at API boundaries. Avoid mocking internal helper calls; fake the generated client/session boundary.

Human reviewability impact: High positive. Refactor PRs can change internals while preserving user-visible behavior.

Confidence: High.

## Refactor Work Items

1. [ ] Generate and alias flow contracts from OpenAPI.
   - Dependencies: Core schemas already exist for `FlowPublic`, `FlowSparsePublic`, `FlowStepPublic`, `FlowRunPublic`, `FlowRunContractPublic`, `FlowRunEvidenceResponse`, and the cited AI Builder plan/session/step types. Verify remaining operation or request-body gaps before adding temporary aliases.
   - Acceptance: Manual flow block in `resources.d.ts` is deleted or replaced by generated aliases; AI Builder protocol duplicate types are removed where generated schemas exist.
   - Tests: `pnpm -C frontend check`; endpoint contract tests.
   - Rollback/recovery: Keep a temporary alias compatibility layer only if specific generated schema gaps are documented with deletion criteria.
   - Risk: Medium; may expose backend schema incompleteness.
   - Reviewability: High positive.
   - Confidence: High.

2. [ ] Pick and document the flow frontend reactivity rule.
   - Dependencies: None.
   - Acceptance: Flow frontend either standardizes new session owners on Svelte 5 runes or documents where legacy `svelte/store` remains and why.
   - Tests: Not applicable beyond existing component tests.
   - Rollback/recovery: ADR can be revised before implementation begins.
   - Risk: Low.
   - Reviewability: High positive.
   - Confidence: Medium.

3. [ ] Collapse AI Builder Driver/Service into one state owner.
   - Dependencies: Work item 1 preferred.
   - Acceptance: No field-by-field state mirror; phase derivation and workflow commands live with the state owner.
   - Tests: AI Builder component auto-resume, streaming session behavior, apply-plan conflict/error handling.
   - Rollback/recovery: Slice the first PR to remove mirroring without moving all UI components.
   - Risk: Medium.
   - Reviewability: High positive.
   - Confidence: High.

4. [ ] Deepen `FlowEditor` into the canonical authoring session.
   - Dependencies: Work item 2.
   - Acceptance: Route and panels no longer mutate steps or metadata directly; commands are typed by domain intent.
   - Tests: Step edit/autosave, reorder/reference remap, form schema metadata, AI Builder apply refresh.
   - Rollback/recovery: Move one mutation path at a time and keep route behavior unchanged.
   - Risk: High if done as one diff; medium if sliced by command boundary. Work item 2 must land before any slice of this work item so the refactor does not introduce another state paradigm.
   - Reviewability: High positive.
   - Confidence: High.

5. [ ] Extract run launch state from `FlowRunDialog.svelte`.
   - Dependencies: Work item 1 preferred.
   - Acceptance: Launch workflow is testable through a session/controller; dialog is mostly rendering and event wiring.
   - Tests: Run dialog component journeys for success, upload/create failure, dirty close, and reset on close.
   - Rollback/recovery: Keep existing pure helpers and move mutable state incrementally.
   - Risk: Medium.
   - Reviewability: High positive.
   - Confidence: High.

6. [ ] Type evidence/progress/status surfaces.
   - Dependencies: Work item 1.
   - Acceptance: Evidence uses generated response type; one typed status primitive owns labels and presentation.
   - Tests: Evidence render test and status presentation test.
   - Rollback/recovery: Start with typed aliases and component-level fixture before visual refactor.
   - Risk: Low to medium.
   - Reviewability: High positive.
   - Confidence: High.

7. [ ] Add missing component journey tests before or during refactors.
   - Dependencies: Stable fake generated client boundary.
   - Acceptance: Critical flow UI paths have behavior tests and do not assert private helper calls.
   - Tests: This item is the tests.
   - Rollback/recovery: If jsdom setup remains broken, fix test environment first and document the blocker.
   - Risk: Medium due to current Phase 0 jsdom environment failure.
   - Reviewability: High positive.
   - Confidence: High.

8. [ ] Delete or schedule legacy frontend compatibility paths.
   - Dependencies: Phase 1b dead-code inventory or owning refactor PRD.
   - Acceptance: `cleanupLegacyMirroredInputTemplates` in `FlowEditor.ts:281-324` and route/client `flow_id` compatibility shims have keep/delete decisions with deletion criteria.
   - Tests: Behavior tests for the kept canonical path only.
   - Rollback/recovery: If a path is kept, document shipped usage and removal trigger.
   - Risk: Low.
   - Reviewability: Medium positive.
   - Confidence: Medium.

## Explicit Non-Goals

- Do not split large Svelte files only to reduce line count.
- Do not add generic `utils`, `helpers`, `manager`, or pass-through service files.
- Do not introduce a third state paradigm while trying to reconcile stores and runes.
- Do not preserve manual flow types for frontend convenience once generated schema aliases are available.
- Do not replace behavior tests with snapshot tests of incidental Svelte output.

## No Findings

| Area | Result |
|---|---|
| SvelteKit `load` side effects in reviewed flow routes | No findings. The reviewed `+page.ts` files load data and validate access without observed client state mutation. |
| Standalone visual primitive issue in `FlowAIBuilderPhaseIndicator.svelte` | No findings. The issue is upstream phase ownership, not the indicator component. |
| Existing pure helper tests for run contract and wizard derivation | No findings. These are useful behavior tests and should be kept. |

## Final Scorecard

Scores use the repository rubric. Overall score is the minimum dimension score.

| Dimension | Score | Rationale |
|---|---:|---|
| Maintainability | 4 | Important workflows are understandable only by reading route state, editor stores, service mirrors, and large components together. |
| Code Quality | 5 | Many helpers are useful and behavior-tested, but public component and API boundaries still use `any`, `unknown`, and broad records. |
| Clean Architecture | 4 | Route, component, service, driver, and API client responsibilities are blurred in flow authoring and AI Builder. |
| Separation of Concerns | 3 | Components own application workflows, especially run launch, evidence parsing, and authoring orchestration. |
| Single Source of Truth | 3 | Flow contracts are manually duplicated, AI Builder state is mirrored, and authoring state is split across route/editor/panels. |
| Human Readability | 4 | Large files and mixed state paradigms make week-one comprehension hard for a senior engineer. |
| Human Reviewability | 4 | Reviewers must trace hidden side effects and callbacks across many files to approve small behavior changes. |
| Testability | 5 | Pure helper and driver tests exist, but critical component journeys and flow E2E coverage are missing. |

Overall score: 3.

Action band: Refactor required before further significant frontend feature work. The first refactor should be the generated flow contract cut, because it shrinks the state ownership and evidence/run dialog fixes instead of layering more local types on top.
