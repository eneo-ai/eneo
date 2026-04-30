# Batch 6 - AI Builder Contract Split

## Frontend AI Builder Protocol Generated Alias Plan

### TL;DR

- Active scope: frontend AI Builder protocol type aliases only.
- Generated OpenAPI schemas are canonical where they already exist in
  `frontend/packages/intric-js/src/types/schema.d.ts`; pure HTTP/API aliases
  move to `frontend/packages/intric-js/src/types/resources.d.ts`, matching the
  existing generated-alias pattern.
- Structural API shapes live in `resources.d.ts`; small feature-scoped
  literal aliases may stay in `protocol.ts` when moving them would create
  cross-package names with no current consumer outside AI Builder.
- Frontend-owned SSE event payloads, edit-result projections, and chat view
  models stay local because generated schemas are missing or the shape is UI
  state rather than HTTP API contract.
- No Driver/Service state-owner work, component UI refactor, backend change,
  generated schema regeneration, package rename, or namespace rename is in
  scope.

### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=12` | latest commit `4230822e docs: record ai builder router thinning no-go` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; dirty files limited to `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, and `PRODUCT.md` |
| `git diff --cached --name-only` | no staged files |

Known unrelated dirty files remain out of scope and must not be touched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

Expected files to change:

- `frontend/packages/intric-js/src/types/resources.d.ts`
- `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderStepCard.svelte`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte`
- AI Builder frontend tests if generated optionality exposes a behavior pin gap
- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/retrospective-6.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-6.md`

Explicitly out of scope:

- Driver/Service state-owner refactor
- component UI redesign
- backend changes
- generated schema regeneration
- `frontend/packages/ui/src/icons/types.d.ts`
- package rename from `@intric/intric-js`
- `intric.*` to `eneo.*` namespace work

### Exported Type Mapping

Consumer counts were gathered with `rg` across
`frontend/apps/web/src`, `frontend/packages/intric-js/src`, and
`frontend/packages/ui/src`.

| type | current owner | generated schema candidate | classification | action | reason | tests |
|---|---|---|---|---|---|---|
| `AIBuilderEventType` | `protocol.ts` | none; `send_ai_builder_message` stream response is generated as `text/event-stream: string` | SSE-only frontend contract | leave local | Event names are not generated as a typed schema. | Driver stream tests |
| `AIBuilderStreamEvent` | `protocol.ts` | none | SSE-only frontend contract | leave local | Transport callback receives plain `{ event, data }` frames. | Driver stream tests |
| `TargetKind` | `protocol.ts` | `components["schemas"]["TargetKind"]` | direct generated alias | replace with generated alias | Backend owns create/edit target kind. | typecheck, Driver tests |
| `SessionStatus` | `protocol.ts` | `components["schemas"]["SessionStatus"]` | direct generated alias | replace with generated alias | Backend owns persisted AI Builder session lifecycle statuses. | typecheck, Driver tests |
| `PlanStatus` | `protocol.ts` | `components["schemas"]["PlanStatus"]` | direct generated alias | replace with generated alias | Backend owns plan lifecycle statuses. | typecheck, Driver tests |
| `AIBuilderPlanEditScope` | `protocol.ts` | missing from generated `SendMessageRequest` despite backend `edit_context` model | generated schema missing | leave local and record gap | Edit context is a request-body schema gap; do not invent generated coverage. | typecheck |
| `AIBuilderPlanEditContext` | `protocol.ts` | missing from generated `SendMessageRequest` despite backend `AIBuilderPlanEditContext` | generated schema missing | leave local and record gap | Frontend sends edit context, but generated `SendMessageRequest` lacks the field. | Driver send-message tests |
| `AIBuilderSuggestChangeIntent` | `protocol.ts` | none | UI-only view model | leave local | Focus/prefill intent is component state, not API contract. | component/typecheck |
| `AIBuilderConversationToolCall` | `protocol.ts` | `components["schemas"]["ConversationMessage"]["tool_calls"][number]` is anonymous primitive JSON | UI/SSE-owned typed projection | leave local | Generated anonymous object does not provide a stable exported contract. | typecheck |
| `AIBuilderConversationMessage` | `protocol.ts` | `components["schemas"]["ConversationMessage"]` has `role: string` | generated alias plus UI projection | keep local narrowed role while reusing generated fields | The UI handles only `user`, `assistant`, `tool`, and `system`; aliasing directly would lose exhaustiveness. | Driver hydration tests |
| `AIBuilderAttachmentFile` | `protocol.ts` | `components["schemas"]["FilePublic"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns attachment file response shape. | component/typecheck |
| `AIBuilderSession` | `protocol.ts` | `components["schemas"]["SessionResponse"]` | generated alias plus UI projection | move raw `SessionResponse` alias to `resources.d.ts`; keep a `protocol.ts` projection overriding `conversation` and `telemetry` | Backend owns session response shape; frontend narrows conversation role and requires defaulted telemetry counters. | Driver tests |
| `AIBuilderDraftSession` | `protocol.ts` | `components["schemas"]["SessionListItemResponse"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Draft recovery list uses session-list item shape; it must not extend full `SessionResponse`. | Driver/draft recovery tests |
| `StepSpec` | `protocol.ts` | `components["schemas"]["StepSpec"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns step spec; UI must handle generated defaulted optional fields. | Step card and plan diff tests |
| `FlowDraftSpecCore` | `protocol.ts` | `components["schemas"]["FlowDraftSpecCore"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns portable draft spec. | typecheck, Driver tests |
| `LintWarning` | `protocol.ts` | `components["schemas"]["LintWarning"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns lint warning contract. | typecheck |
| `PlannerPlanEnvelope` | `protocol.ts` | `components["schemas"]["PlannerPlanEnvelope"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns plan envelope; UI must tolerate defaulted optional arrays. | Plan pane typecheck |
| `StepChangeKind` | `protocol.ts` | none | UI-only view model | leave local | Edit result schema is not generated; used for UI diff rendering. | plan diff tests |
| `StepChange` | `protocol.ts` | none | UI-only view model | leave local | Edit diff schema is currently SSE/UI projection only. | plan diff tests |
| `FlowEditDiff` | `protocol.ts` | none; HTTP `PlanResponse` has generic `edit_result_json` | generated schema missing | leave local and record gap | Backend does not expose a generated edit diff schema. | plan diff tests |
| `EditConfidence` | `protocol.ts` | none | generated schema missing | leave local and record gap | Edit result confidence is emitted in SSE plan events, not generated. | typecheck |
| `EditAdvisory` | `protocol.ts` | none | generated schema missing | leave local and record gap | Edit advisories are SSE/UI plan metadata, not generated. | Plan pane typecheck |
| `ProposedPlan` | `protocol.ts` | `components["schemas"]["PlanResponse"]` | generated alias plus UI projection | define from generated `PlanResponse` plus local SSE edit-result extensions | HTTP plan response is generated; SSE plan event lacks `session_id`/`spec_hash` and adds edit metadata not in OpenAPI. | Driver/plan pane tests |
| `ApplyError` | `protocol.ts` | none | UI-only view model | leave local | Stale/apply conflict details are frontend error-view state. | typecheck |
| `PlanRevisionType` | `protocol.ts` | `components["schemas"]["RevisePlanRequest"]["type"]` | direct generated alias | replace with generated alias | Backend owns revise request literal. | Driver revise tests |
| `ApplyResult` | `protocol.ts` | `components["schemas"]["ApplyResultResponse"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns apply result response. | Driver apply tests |
| `KeyDecision` | `protocol.ts` | none; backend event payload schema is not generated | SSE-only frontend contract | leave local | Requirements summary events are not generated. | Driver summary tests |
| `RequirementsSummary` | `protocol.ts` | none; backend `RequirementsSummaryPayload` is not generated | SSE-only frontend contract | leave local and record gap | Requirements summary is an SSE event payload. | Driver summary tests |
| `AIBuilderPhase` | `protocol.ts` | none | UI-only view model | leave local | Derived frontend phase, not backend state. | phase indicator/typecheck |
| `ChatMessage` | `protocol.ts` | none | UI-only view model | leave local | Frontend chat timeline combines text, plan, questions, summaries, and metadata. | Driver tests |
| `AIBuilderModel` | `protocol.ts` | `components["schemas"]["SessionModelOption"]` | direct generated alias | move API alias to `resources.d.ts`, re-export from `protocol.ts` | Backend owns model option response shape. | Driver model tests |
| `AIBuilderTextEventData` | `protocol.ts` | none | SSE-only frontend contract | leave local | AI Builder SSE payload schema is not generated. | Driver stream tests |
| `AIBuilderStatusEventData` | `protocol.ts` | none | SSE-only frontend contract | leave local | AI Builder SSE payload schema is not generated. | Driver stream tests |
| `AIBuilderErrorEventData` | `protocol.ts` | none | SSE-only frontend contract | leave local | AI Builder SSE payload schema is not generated. | Driver stream tests |
| `AIBuilderQuestionEventData` | `protocol.ts` | none | SSE-only frontend contract | leave local | Structured question event schema is frontend-owned until generated. | Driver/question tests |
| `AIBuilderTelemetrySummary` | `protocol.ts` | `components["schemas"]["SessionTelemetrySummary"]` | generated alias plus UI projection | move raw API alias to `resources.d.ts`; keep generated-backed `Required<>` projection in `protocol.ts` | UI currently expects backend defaulted counters to exist; fixture pins the full contract. | token usage tests |
| `AIBuilderUsageEventData` | `protocol.ts` | `components["schemas"]["SessionTelemetrySummary"]` | generated alias plus UI projection | alias to `AIBuilderTelemetrySummary` | Usage event payload is the session telemetry contract. | token usage and Driver stream tests |

### Exact Projection Shapes

`AIBuilderConversationMessage` keeps the frontend role union while deriving
every non-role field from the generated conversation message schema:

```ts
export type AIBuilderConversationMessage = Omit<
  GeneratedAIBuilderConversationMessage,
  "role" | "tool_calls"
> & {
  role: "user" | "assistant" | "tool" | "system";
  tool_calls?: AIBuilderConversationToolCall[] | null;
};
```

`ProposedPlan` encodes the current HTTP/SSE asymmetry instead of pretending SSE
plan events carry HTTP-only fields:

```ts
type GeneratedPlanHttpFields = Pick<
  GeneratedAIBuilderPlanResponse,
  "session_id" | "spec_hash" | "created_at" | "updated_at" | "edit_result_json"
>;

export type ProposedPlan = Omit<GeneratedAIBuilderPlanResponse, keyof GeneratedPlanHttpFields> &
  Partial<GeneratedPlanHttpFields> & {
    edit_diff?: FlowEditDiff | null;
    edit_confidence?: EditConfidence | null;
    edit_warnings?: string[] | null;
    edit_advisories?: EditAdvisory[] | null;
    edit_risk_flags?: string[] | null;
  };
```

`AIBuilderSession` uses the generated session response but overrides the two
fields where the frontend intentionally projects the generated schema:

```ts
export type AIBuilderSession = Omit<
  GeneratedAIBuilderSessionResponse,
  "conversation" | "telemetry"
> & {
  conversation?: AIBuilderConversationMessage[];
  telemetry?: AIBuilderTelemetrySummary | null;
};
```

`AIBuilderTelemetrySummary` keeps the generated telemetry keys but requires
backend-defaulted counters for the current UI fixture contract:

```ts
export type AIBuilderTelemetrySummary = Required<GeneratedAIBuilderTelemetrySummary>;
```

`Required<>` removes `undefined`; generated nullable `last_*` fields still
remain `string | null`, so UI code must continue to use null-safe reads.

### Consumer Migration Table

| consumer | shape change | mitigation | test |
|---|---|---|---|
| `FlowAIBuilderStepCard.svelte` reads `step.assistant_spec.knowledge_refs.length` | generated `AssistantSpec.knowledge_refs?: string[]` | derive `knowledgeRefs = step.assistant_spec.knowledge_refs ?? []` | `FlowAIBuilderStepCard.test.ts` |
| `FlowAIBuilderStepCard.svelte` renders `step.input_type` | generated `StepSpec.input_type?: AIBuilderInputType` with backend default `text` | derive `inputType = step.input_type ?? "text"` | `FlowAIBuilderStepCard.test.ts` |
| `FlowAIBuilderStepCard.svelte` renders `step.output_type` | generated `StepSpec.output_type?: FlowOutputType` with backend default `text` | derive `outputType = step.output_type ?? "text"` | `FlowAIBuilderStepCard.test.ts` |
| `FlowAIBuilderStepCard.svelte` compares `step.output_mode !== "pass_through"` | generated `StepSpec.output_mode?: AIBuilderOutputMode` with backend default `pass_through` | derive `outputMode = step.output_mode ?? "pass_through"` | `FlowAIBuilderStepCard.test.ts` |
| `FlowAIBuilderPlanPane.svelte` reads `plan.envelope.assumptions.length` and iterates assumptions | generated `PlannerPlanEnvelope.assumptions?: string[]` | derive `planAssumptions = service.currentPlan?.envelope.assumptions ?? []` | app check |
| `FlowAIBuilderPlanPane.svelte` reads and iterates `plan.envelope.lint_warnings` | generated `PlannerPlanEnvelope.lint_warnings?: LintWarning[]` | derive `planLintWarnings = service.currentPlan?.envelope.lint_warnings ?? []` | app check |
| `FlowAIBuilderPlanPane.svelte` reads `spec.flow_description` | generated `FlowDraftSpecCore.flow_description?: string` | current short-circuit read is safe; no code change needed | app check |
| `FlowAIBuilderPlanPane.svelte` reads `plan.envelope.plan_rationale` | generated `PlannerPlanEnvelope.plan_rationale?: string | null` | current short-circuit read is safe; no code change needed | app check |
| `PlannerPlanEnvelope.risk_acknowledgments` | generated field is optional | no UI consumer; only existing test fixture supplies an empty array | typecheck |
| `PlannerPlanEnvelope.reasoning` | generated field is optional and stripped from public responses | no UI consumer | typecheck |
| `FlowAIBuilderPlanPane.svelte` renders `field.required` | generated `FormFieldSpec.required?: boolean` with backend default `false` | render `field.required === true` | app check |
| `AIBuilderDraftSession` consumers | generated draft list item is not a full session response | alias to `SessionListItemResponse`; grep confirms no reads of `draft.attachments`, `draft.conversation`, `draft.telemetry`, or `draft.attachment_warnings` | Driver/draft recovery tests |
| `AIBuilderSession` consumers | raw generated session has wide conversation roles and optional telemetry counters | keep a `protocol.ts` session projection overriding `conversation` and `telemetry` | Driver hydration and token usage tests |
| `AIBuilderConversationMessage.role` consumers | generated role is `string`; local role union is narrower | keep local narrowed projection around generated message fields | Driver hydration tests |
| `ProposedPlan` callers | HTTP `PlanResponse` and SSE plan event are not identical | keep a UI projection, record carry-forward trigger below | Driver/plan pane tests |

Pre-edit grep evidence:

```bash
rg -n "draft\.(attachments|conversation|telemetry|attachment_warnings)" frontend/apps/web/src
```

Result: no matches.

```bash
rg -n "envelope\.(assumptions|lint_warnings)" frontend/apps/web/src
```

Result: only `FlowAIBuilderPlanPane.svelte` reads those fields.

```text
frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:367
frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:373
frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:457
frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderPlanPane.svelte:478
```

```bash
rg --pcre2 -n "A\.[0-9](?![0-9])|P0\.|Phase [0A-G]|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)|frontend protocol slice|Batch 6|6f|as any|@ts-ignore|@ts-expect-error" \
  frontend/apps/web/src/lib/features/flows/ai-builder \
  docs/refactor/prd \
  docs/refactor/ai-builder-prompt-contract.md
```

Result: no matches before source edits.

### Carry-Forward Contract Gaps

- `SendMessageRequest` generated schema lacks `edit_context`, even though the
  backend request model accepts it. Batch 6 keeps `AIBuilderPlanEditContext`
  local. Re-entry trigger: PRD-004/API-source cleanup should expose a generated
  edit-context schema before the frontend deletes the local request contract.
- `PlanResponse` generated schema exposes `edit_result_json`, while SSE plan
  events emit structured `edit_diff`, `edit_confidence`, `edit_warnings`,
  `edit_advisories`, and `edit_risk_flags`. This slice keeps a single UI
  `ProposedPlan` projection because the Driver stores both HTTP and SSE plan
  results in one state slot. Re-entry trigger: split HTTP plan response from SSE
  plan-event projection or add generated structured edit fields before removing
  the local edit-result types.
- AI Builder SSE event payload schemas are not generated. Keep local SSE event
  payload contracts until the backend/OpenAPI source exposes generated schemas
  for `text`, `status`, `error`, `question`, `requirements_summary`, and plan
  event payloads.
- Lower-level local UI/SSE helpers such as `AIBuilderPlanEditScope`,
  `StepChange`, `EditConfidence`, `EditAdvisory`, and `RequirementsSummary`
  are intentionally not tracked as separate migration gaps; they are covered by
  the broader edit-context, edit-result, and SSE payload schema gaps above.

### Behavior Pins Before Implementation

- `FlowAIBuilderDriver.test.ts` already pins session create/resume, stream
  event handling, plan/apply/revise behavior, and draft recovery.
- `flowAIBuilderPlanDiff.test.ts` pins edit diff behavior over `StepSpec`.
- `FlowAIBuilderStepCard.test.ts` pins step rendering over `StepSpec`.
- `flowAIBuilderTokenUsage.test.ts` pins telemetry key coverage against the
  backend fixture.

If generated optionality changes component behavior, update only behavior tests
that exercise the visible behavior. Do not add tests that assert type aliases
by private implementation details.

### Validation Commands

Batch 6 validation labels are AI Builder integration tests, SSE event tests,
and frontend AI Builder tests. For this frontend-only slice the exact commands
are:

```bash
cd frontend/packages/intric-js && bun run check
```

```bash
cd frontend/packages/intric-js && bun run lint
```

```bash
cd frontend/apps/web && bun test src/lib/features/flows/ai-builder
```

```bash
cd frontend/apps/web && bun run check
```

```bash
git diff --check -- frontend/apps/web/src/lib/features/flows/ai-builder frontend/packages/intric-js docs/refactor/execution/batch-6-ai-builder-contract-split
```

Anti-slippage guard:

```bash
rg --pcre2 -n "A\.[0-9](?![0-9])|P0\.|Phase [0A-G]|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)|frontend protocol slice|Batch 6|6f|as any|@ts-ignore|@ts-expect-error" \
  frontend/apps/web/src/lib/features/flows/ai-builder \
  docs/refactor/prd \
  docs/refactor/ai-builder-prompt-contract.md
```

Expected: no matches in touched source. The `A\.[0-9](?![0-9])` form avoids
false positives from SVG path data such as `A.75`. Existing
`docs/refactor/execution/*` process artifacts are excluded from the guard.

## TL;DR

- Active scope: AI Builder router/presenter thinning no-go decision.
- Chosen path: Path C. No production source/test extraction ships from this
  slice.
- Path A is rejected because moving stream finalization to `ai_builder_events.py`
  would turn a pure event-builder module into an async presenter with service,
  request-context, logging, and error-finalization concerns.
- Path B is rejected because the response-view helpers are small HTTP adapter
  mappings and moving them would create a weak file split without thinning the
  SSE wrapper that PRD-005 names.
- The prompt/audit, repair retry, create/edit proposal, and send-lock no-go
  checkpoints are archived below; none of them is active implementation scope.

## Router/Presenter Thinning Plan

### Start Gate

| Check | Result |
|---|---|
| `git log -1 --oneline` | `ade08599 docs: archive ai builder send-lock no-go iteration` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; dirty files limited to `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, and `PRODUCT.md` |
| `git diff --cached --name-only` | no staged files |
| Docker check | `docker ps --format '{{.Names}}'` blocked by host execution policy with `approval required by policy, but AskForApproval is set to Never`; local fallback validation planned |

Known unrelated dirty files remain out of scope and must not be touched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

This slice thins only the AI Builder router/presenter surface. It may touch:

- `backend/src/intric/flows/ai_builder/ai_builder_router.py`
- `backend/src/intric/flows/ai_builder/ai_builder_events.py`
- AI Builder router/SSE behavior tests
- this batch's process artifacts

Optional file only if Path B is selected in a future plan:

- `backend/src/intric/flows/ai_builder/ai_builder_response_views.py`

Explicitly out of scope:

- planner/send-lock extraction
- `ai_builder_planner.py`
- `ai_builder_planner_turn.py`
- proposal processor changes
- edit proposal changes
- repair changes
- frontend protocol work
- package rename
- `intric.*` to `eneo.*` namespace rename
- migrations
- data model changes
- OpenAPI decorator metadata restructuring

`backend/src/intric/flows/ai_builder/ai_builder_events.py` is the canonical SSE
event construction owner for this slice. It was read end to end before any
production edit. It already owns event names and builders at
`backend/src/intric/flows/ai_builder/ai_builder_events.py:22-165`.

### Pre-Edit Baseline

Before any production edit, the focused happy-path router stream baseline ran:

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_router.py::TestSendMessageEndpoint::test_streams_usage_event_after_committed_message_event -q
```

Result: pass, 1 passed.

Current happy-path SSE event order from that test:

```text
plan -> usage -> done
```

The path must preserve that order. The existing router tests also pin:

- usage emitted before done:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1135-1189`
- late usage emitted before done:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1191-1253`
- pre-existing usage not duplicated:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1255-1282`
- generic stream error followed by done:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1500-1532`
- `BadRequestException` followed by done:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1534-1568`

### Measured Inventory

The `proposed owner` column records the owner considered during the rejected
Path A / Path B analysis. The active decision is Path C no-go, so no row moves
in this iteration.

| symbol / block | file:line | LOC estimate | responsibility | classification | proposed owner | does moving reduce AIBuilderPlanner.send_message? | reason |
|---|---|---:|---|---|---|---|---|
| `_coerce_event_stream` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:98-103` | 6 | Normalize an async generator or awaitable stream returned by the service seam. | move to `ai_builder_events.py` | `ai_builder_events.py` | no | Honest pure-stream candidate, but too small alone to earn the slice. No move in Path C. |
| `_current_usage_event` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:106-117` | 12 | Read current session telemetry and build a usage event. | move to `ai_builder_events.py` | `ai_builder_events.py` | no | Rejected: moving it would drag service/telemetry lookup into event code or force a callback seam. |
| `_resolve_litellm_params` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:120-124` | 5 | Thin router-level planner parameter test seam. | keep in router | router | no | Explicit non-move. It is not presenter/view code and remains tied to request preparation. |
| `_to_plan_response` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:222-233` | 12 | Convert stored plan to public response while stripping reasoning. | leave for later | future `ai_builder_response_views.py` only if Path B is approved | no | Meaningful response mapping, but Path B is rejected until response-view duplication or a non-router caller appears. |
| `_to_file_public` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:236-239` | 4 | Normalize stored attachment file to public file response. | leave for later | internal helper only with `_to_session_response` in future Path B | no | Too small to export by itself; only moves if response views earn a module. |
| `_to_session_response` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:242-265` | 24 | Convert session domain object to public response with telemetry and attachment defaults. | leave for later | future `ai_builder_response_views.py` only if Path B is approved | no | Good Path B candidate only after a real response-view trigger. Existing tests pin defaults at `test_ai_builder_router.py:502-614`. |
| `_ai_builder_error_response` | `backend/src/intric/flows/ai_builder/ai_builder_router.py:268-288` | 21 | Build OpenAPI JSON error response examples. | keep in router | router | no | Explicit non-move. It is decorator metadata, not runtime presenter code. |
| OpenAPI `responses=` metadata | `backend/src/intric/flows/ai_builder/ai_builder_router.py:303-319`, `378-387`, `437-473`, `626-640`, `705-719`, `760-774`, `805-819`, `852-866`, `914-928`, `980-1010`, `1091-1105` | large but excluded from gate | Endpoint documentation and generated OpenAPI contract. | keep in router | router | no | Explicitly excluded from success gates and not part of runtime presenter behavior. |
| `send_message` stream finalization loop | `backend/src/intric/flows/ai_builder/ai_builder_router.py:531-578` | 48 | Defers done, tracks committed/error/usage events, auto-emits usage, emits done last. | move to `ai_builder_events.py` | `ai_builder_events.py` | no | Rejected: it carries cross-event presenter state and couples to usage lookup. |
| `send_message` error-to-done finalization | `backend/src/intric/flows/ai_builder/ai_builder_router.py:579-615` | 37 | Convert stream exceptions to SSE error followed by done. | move to `ai_builder_events.py` | `ai_builder_events.py` | no | Rejected: request correlation, logging context, and router error translation belong with the router. |
| `send_message` request/auth/context setup | `backend/src/intric/flows/ai_builder/ai_builder_router.py:475-529` | 55 | HTTP request handling, auth, tenant/model/context preparation, service invocation. | keep in router | router | no | Router adapter responsibility. Moving this would start planner/service work. |
| `create_session` inline response/audit shaping | `backend/src/intric/flows/ai_builder/ai_builder_router.py:320-369` | 50 | Create session, attachment response shaping, audit metadata. | keep in router | router | no | Audit and HTTP endpoint behavior stay in router; response mapping may be considered later under Path B. |
| `list_sessions` permission filtering | `backend/src/intric/flows/ai_builder/ai_builder_router.py:389-426` | 38 | Visible-session filtering by scope and space edit permission. | keep in router | router | no | Authorization/filtering adapter behavior, not presenter code. |
| `get_session` response mapping | `backend/src/intric/flows/ai_builder/ai_builder_router.py:643-669` | 27 | Load session/attachments and return session response. | leave for later | future `ai_builder_response_views.py` only if Path B is approved | no | Tied to `_to_session_response`; not moved in Path A. |
| `get_plan` response mapping | `backend/src/intric/flows/ai_builder/ai_builder_router.py:777-796` | 20 | Load plan/session, authorize, return plan response. | leave for later | future `ai_builder_response_views.py` only if Path B is approved | no | Tied to `_to_plan_response`; not moved in Path A. |
| `list_session_plans` response mapping | `backend/src/intric/flows/ai_builder/ai_builder_router.py:822-843` | 22 | Load session plans and map each to public response. | leave for later | future `ai_builder_response_views.py` only if Path B is approved | no | Response-view candidate, but Path A chosen. |
| `approve_plan` inline audit/response | `backend/src/intric/flows/ai_builder/ai_builder_router.py:931-970` | 40 | Approve plan, audit metadata, response model. | keep in router | router | no | Audit stays in router. Response is small. |
| `apply_plan` stale-revision JSON response and audit | `backend/src/intric/flows/ai_builder/ai_builder_router.py:1013-1079` | 67 | Apply plan, HTTP 409 envelope, audit metadata, response. | keep in router | router | no | HTTP error-envelope and audit behavior are explicit router responsibilities. |
| `revise_plan` response mapping | `backend/src/intric/flows/ai_builder/ai_builder_router.py:1107-1134` | 28 | Revise plan and return public plan response. | leave for later | future `ai_builder_response_views.py` only if Path B is approved | no | Response-view candidate, but Path A chosen. |

### Path Choice

Chosen path: **Path C - no-go**.

Path A was considered first because `ai_builder_events.py` is the existing SSE
event construction owner. It is rejected after plan review for these reasons:

- `ai_builder_events.py` is currently a pure synchronous event-builder module:
  public functions build event dictionaries and do not orchestrate streams
  (`backend/src/intric/flows/ai_builder/ai_builder_events.py:32-165`).
- The proposed stream finalizer would own cross-event state from
  `backend/src/intric/flows/ai_builder/ai_builder_router.py:531-578`, call
  `service.get_session(...)` through `_current_usage_event` at
  `ai_builder_router.py:106-117`, and map/log request-context exceptions from
  `ai_builder_router.py:579-615`.
- Moving those concerns would either import application service and telemetry
  dependencies into `ai_builder_events.py`, introduce a callback/parameter-bag
  seam, or split error finalization between modules. All three are weaker than
  keeping the current router-owned SSE adapter behavior.
- Moving only `_coerce_event_stream` is honest but too small to satisfy the
  slice's value gate or PRD-005 router thinning intent.

Path B was considered and rejected for this slice:

- `_to_plan_response`, `_to_session_response`, and `_to_file_public` are small
  HTTP response mapping helpers, totaling roughly 42 LOC.
- They are legitimate HTTP adapter responsibilities. Moving them would create a
  small response-view file without thinning the send-message SSE wrapper that
  PRD-005 names.
- Reopen response-view extraction only if a non-router caller appears or at
  least three response mappers become duplicated across owners.

Decision:

- make no source changes
- add no tests in this no-go slice because existing router tests already pin the
  observable SSE order and error/done behavior
- record the inventory, failed path choice, rationale, and PRD-005 carry-forward
  in the journal
- keep PRD-005 router thinning open/carry-forward

PRD-005 acceptance criteria are not modified by this no-go. `Router SSE wrapper
is thin` remains open/carry-forward.

Carry-forward trigger:

Reopen router/presenter thinning only when there is measured evidence that one
of these is true:

- the send-message SSE wrapper can shed a real lifecycle responsibility without
  moving service/request/logging concerns into `ai_builder_events.py`, or
- a named event-stream presenter module is explicitly approved with a dependency
  budget, net-LOC gate, and full signature before implementation, or
- response-view duplication appears outside the router and makes
  `ai_builder_response_views.py` a real canonical owner rather than a small
  file split.

### Behavior Pins And Invariants

This slice adds no tests; the list below documents the contract any future
router-thinning slice must protect.

- happy-path SSE event order: `plan -> usage -> done`
- usage event emitted before done
- done event deferred until usage has emitted
- usage auto-emitted only when committed success occurred and no stream error
  was seen
- pre-existing usage event forwarded without duplicate
- error event followed by done for `BadRequestException`
- error event followed by done for generic exception path
- `PlanResponse.envelope.reasoning` remains stripped to `None`
- `_to_session_response` defaults remain stable:
  - `attachments=[]`
  - `attachment_warnings=[]`
  - telemetry `None` passthrough
- audit metadata remains unchanged
- router auth/dependency behavior remains unchanged
- prompt-contract artifact still passes
- proposal/edit/repair behavior remains unchanged

Testing strategy if this slice reopens:

- Keep router endpoint behavior tests in `test_ai_builder_router.py`.
- Keep router tests as the canonical SSE-order contract. If events tests are
  added later, they should cover only behavior not reachable through router
  tests, such as pure stream-shape normalization.
- Do not create tests for a generic presenter object or implementation-detail
  call order.

### Expected Files To Change

Expected source:

- none

Expected tests:

- none

Expected process docs:

- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/retrospective-5.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-5.md`

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- `backend/src/intric/flows/ai_builder/ai_builder_planner.py`
- `backend/src/intric/flows/ai_builder/ai_builder_planner_turn.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py`
- `backend/src/intric/flows/ai_builder/ai_builder_repair.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py`
- frontend files
- migrations
- OpenAPI decorator metadata structure

### Validation Commands

Implementation-order row for Batch 6 gives validation labels:

- AI Builder integration tests
- SSE event tests
- frontend AI Builder tests

For this no-go slice, exact validation commands are:

Baseline stream order already run before no-go decision:

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_router.py::TestSendMessageEndpoint::test_streams_usage_event_after_committed_message_event -q
```

Diff hygiene:

```bash
git diff --check -- \
  docs/refactor/execution/batch-6-ai-builder-contract-split
```

Source/test cleanliness:

```bash
git diff --name-only -- backend/src backend/tests
```

Staged-file cleanliness:

```bash
git diff --cached --name-only
```

Anti-slippage guard:

```bash
rg -n "A\.[0-9]|P0\.|Phase [0A-G]|/tmp/ai_builder|plan/(phases|progress|briefs|intents|reviews|codex|architecture_plan)|sectioned intake slice|router/presenter slice|Batch 6|6e" \
  backend/src backend/tests docs/refactor/prd docs/refactor/ai-builder-prompt-contract.md
```

Expected: no matches.

Frontend AI Builder tests are not run because this slice forbids frontend edits
and does not change frontend protocol surfaces. If implementation reveals a
frontend-facing contract risk, stop and ask for a scope decision.

### Claude Plan Review

Claude peer-loop challenged the initial Path A plan and returned
`changes_required`, `GREEN_LIGHT: no`, and `MIN_SCORE: 6`. Accepted findings:

- moving stream finalization to `ai_builder_events.py` would change that module
  from pure event builders into an async presenter
- `_current_usage_event` would drag `AIBuilderService` or callback-bag
  dependency into event code
- error-to-done finalization needs request/logging context that belongs in the
  router
- the Path A gate was too weak because it lacked net LOC, import-boundary, and
  signature-width failure conditions
- duplicate events tests would compete with existing router SSE contract tests

This revised plan chooses Path C no-go. Run Claude peer-loop verification
against this revision before ending the loop.

## Archived No-Go Iterations

### Planner send-lock lifecycle extraction

Attempted goal: extract planner send-lock claim, refresh, lease-lost detection,
and release behavior out of `AIBuilderPlanner.send_message` into one concrete
async context manager without changing planner, SSE, chained-call, audit,
repair, proposal, frontend, or persistence semantics.

Extraction gate:

- consolidate at least three send-lock/lease helpers
- reduce `AIBuilderPlanner.send_message` by at least 80 LOC
- keep `ai_builder_planner_send_lock.py` at or below 150 LOC
- avoid net production LOC growth

Measured result:

| Measure | Result |
|---|---:|
| Baseline `AIBuilderPlanner.send_message` | 595 LOC |
| Draft `AIBuilderPlanner.send_message` | 568 LOC |
| Reduction | 27 LOC |
| Required reduction | 80 LOC |
| Draft `ai_builder_planner_send_lock.py` | 163 LOC |
| Module cap | 150 LOC |

Decision: no production source/test extraction ships from this iteration.

Why: the proposed module did not earn its existence under the plan's own gate.
The implementation preserved behavior, SSE/error mapping, chained-call, and
refresh-task cleanup constraints, but those constraints left only 27 LOC
removable from `send_message`; the new module also exceeded the 150 LOC cap.
Shipping that shape would create a shallow lifecycle module rather than a
clearer ownership boundary.

The source/test draft was reverted. No production source/test changes from this
iteration should remain in the working tree. `ai_builder_planner_turn.py`
already exists and must not be recreated.

PRD-005 planner-turn lifecycle ownership remains open/carry-forward.
PRD-005 acceptance criteria are not modified by this cleanup pass.
`Planner turn lifecycle has one owner` remains open/carry-forward unless a
later human-approved PRD decision changes it.

Reopen planner-flow/send-lock extraction only after router/presenter thinning
has landed and there is measured evidence that either:

- `AIBuilderPlanner.send_message` can be reduced by at least 80 LOC without
  creating a pass-through lifecycle module, or
- a broader planner-flow owner can absorb lock, chained server action, and
  error/SSE boundary behavior as one real lifecycle concept.

If later evidence shows this responsibility should intentionally remain in
`AIBuilderPlanner`, PRD-005 must be updated in a separate human-approved PRD
decision rather than silently treating this criterion as done.

#### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=8` | latest commit is `af898af4 flows: separate ai builder edit proposal processing` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; dirty files limited to `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, and `PRODUCT.md` before this plan update |
| `git diff --cached --name-only` | no staged files |
| Docker check | `docker ps --format '{{.Names}}'` blocked by host execution policy with `approval required by policy, but AskForApproval is set to Never`; local fallback validation planned |

Known unrelated dirty files are out of scope and must remain untouched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

#### Scope

This slice extracts and hardens only the planner send-lock lifecycle around
`AIBuilderPlanner.send_message`. It does not create a planner-turn module:
`backend/src/intric/flows/ai_builder/ai_builder_planner_turn.py` already owns
the planner pipeline/dispatcher bridge.

PRD-005 constraints that govern this slice:

- "No fake one-method interfaces are introduced."
- "no interface unless two real implementations exist."

Default structural decision:

- Add at most one production module:
  `backend/src/intric/flows/ai_builder/ai_builder_planner_send_lock.py`.
- Add one concrete async context manager:
  `PlannerTurnSendLock`.
- Keep `run_planner_turn`, `dispatch_planner_action`, `repo.commit_turn`,
  prompt assembly, proposal processing, repair behavior, chained server actions,
  SSE formatting, router behavior, audit behavior, and frontend behavior in
  their current owners.
- Do not create a Protocol, ABC, factory, compatibility wrapper, re-export,
  generic lock helper, telemetry dataclass, migration, or namespace/package
  rename.

#### Required Pre-Diff Inventory Commands

These commands ran before any production diff:

```bash
docker ps --format '{{.Names}}'
```

Result: blocked by host execution policy:

```text
CreateProcess { message: "Rejected(\"approval required by policy, but AskForApproval is set to Never\")" }
```

```bash
git grep -n "claim_session_send\|refresh_session_send_lease\|release_session_send\|_send_lock_lease_seconds\|_next_send_lock_expiry\|_send_lock_refresh_interval_seconds\|_maintain_send_lock_lease\|_dispatch_chained_server_action_after_commit\|run_planner_turn\|commit_turn" -- backend/src backend/tests
```

Key result:

- `AIBuilderPlanner` owns the send-lock helper cluster at
  `backend/src/intric/flows/ai_builder/ai_builder_planner.py:337-397`.
- `AIBuilderPlanner.send_message` claims the lock, creates refresh state/task,
  and releases the lock at
  `backend/src/intric/flows/ai_builder/ai_builder_planner.py:994-1019` and
  `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1519-1536`.
- Lease-lost SSE mapping is duplicated in the caller at
  `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1327-1339` and
  `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1356-1367`.
- The chained post-commit server action stays in
  `backend/src/intric/flows/ai_builder/ai_builder_planner.py:775-896`.
- `run_planner_turn` stays in
  `backend/src/intric/flows/ai_builder/ai_builder_planner_turn.py:134-152`.
- `repo.commit_turn` remains the persistence/transaction boundary through
  `backend/src/intric/flows/ai_builder/ai_builder_dispatcher.py:121-130` and
  `backend/src/intric/flows/ai_builder/ai_builder_repo.py:973`.
- Repository lock primitives stay in
  `backend/src/intric/flows/ai_builder/ai_builder_repo.py:646-735`.
- Existing unit pins for send-message outcomes live in
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py`.
- Existing DB pins for claim/release/lease-lost commit behavior live in
  `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:419-528`
  and `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:1191-1236`.

#### Extraction Gate

Proceed with production extraction only if both gates remain true after the
first implementation draft:

| Gate | Planned proof |
|---|---|
| Consolidates at least 3 send-lock/lease helpers | Move `_send_lock_lease_seconds`, `_next_send_lock_expiry`, `_send_lock_refresh_interval_seconds`, and `_maintain_send_lock_lease` into `PlannerTurnSendLock`. |
| Reduces `AIBuilderPlanner.send_message` by at least 80 LOC | Replace the claim/task/finally lifecycle block with `async with PlannerTurnSendLock(...)`, remove duplicated lease-lost event construction by using a local caller-owned event builder inside `send_message`, and remove the moved helper cluster from `AIBuilderPlanner`. |

If either gate fails after formatting, stop, revert the production draft, and
record a no-production-change result in this journal instead of shipping a weak
module.

Current measured baseline:

- `AIBuilderPlanner.send_message`: 595 LOC.
- Candidate displaced lock/lease spans:
  - send-lock helper cluster: 61 LOC
  - claim block: 26 LOC
  - `BadRequestException(code="session_send_lease_lost")` SSE block: 13 LOC
  - lease-lost poll SSE block: 12 LOC
  - final release block: 18 LOC
  - total candidate displacement: 130 LOC

Post-change proof must record the new `send_message` LOC and the new module
LOC in the journal before the implementation is accepted.

#### Implementation Gate Result

The first implementation draft failed the extraction gate:

| Gate | Result |
|---|---|
| Consolidates at least 3 helpers | Would have passed: the draft moved `_send_lock_lease_seconds`, `_next_send_lock_expiry`, `_send_lock_refresh_interval_seconds`, and `_maintain_send_lock_lease`. |
| Reduces `AIBuilderPlanner.send_message` by at least 80 LOC | Failed: baseline was 595 LOC; the draft left `send_message` at 568 LOC, a 27 LOC reduction. |
| New module <=150 LOC | Failed: the draft `ai_builder_planner_send_lock.py` was 163 LOC. |
| Net production LOC must not increase | Failed risk: the module cap failed before net LOC was accepted. |

Per the gate, the source/test draft was reverted. This slice should not ship a
weak lock module. The next attempt needs a smaller, cleaner plan, likely either:

- a no-production-change decision that leaves send-lock lifecycle in the planner
  until router/presenter thinning creates a clearer boundary, or
- a broader, explicitly approved planner-flow extraction that reduces
  `send_message` by moving a real lifecycle responsibility rather than only
  moving lock plumbing.

#### Inventory And Movement Decisions

| name | file:line | responsibility | current owner | decision (stays / moves to ai_builder_planner_send_lock.py) | reason |
|---|---|---|---|---|---|
| `_send_lock_lease_seconds` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:337-339` | compute configured lease seconds with lower bound | `AIBuilderPlanner` | moves | It is send-lock lifecycle policy, not prompt/planner behavior. |
| `_next_send_lock_expiry` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:341-345` | compute next lease expiry timestamp | `AIBuilderPlanner` | moves | It belongs with claim/refresh lease ownership. |
| `_send_lock_refresh_interval_seconds` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:347-349` | compute refresh cadence from lease length | `AIBuilderPlanner` | moves | It is refresh-loop policy and should live with the background lease task. |
| `_maintain_send_lock_lease` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:351-397` | background lease refresh and lease-lost detection | `AIBuilderPlanner` | moves | This is the largest send-lock lifecycle helper and uses only repo, tenant/request/session, token, stop, and lost-event state. |
| claim path | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:994-1019` | request/lock token creation, DB claim, refresh task start | `AIBuilderPlanner.send_message` | moves | `PlannerTurnSendLock.__aenter__` should claim the lock and start refresh only after a successful claim. |
| refresh path | `backend/src/intric/flows/ai_builder/ai_builder_repo.py:685-712` | DB lease refresh with matching request/token | `AIBuilderRepository` | stays | Repository remains the persistence owner; lock context manager only calls it. |
| release path | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1519-1536`, `backend/src/intric/flows/ai_builder/ai_builder_repo.py:714-735` | stop refresh task and release matching request/token | planner caller plus repository | moves from planner caller / repository stays | Context manager owns idempotent release and task cleanup; repository remains DB owner. |
| lease expiry calculation | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:337-349` | minimum lease and refresh timing policy | `AIBuilderPlanner` | moves | Co-locate with send-lock lifecycle state. |
| background lease task | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1011-1019`, `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1519-1530` | start, stop, await, and warn on refresh task | `AIBuilderPlanner.send_message` | moves | It is lifecycle plumbing and should be hidden behind the context manager. |
| lease-lost detection | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:385-397`, `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1356-1367` | signal lost lease and map to existing SSE error | mixed helper + caller | signal moves / SSE stays | `PlannerTurnSendLock.lease_lost_event` remains the signal; `send_message` keeps the event shape and `BadRequestException` mapping. |
| `send_message` claim/task/finally behavior | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:994-1019`, `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1519-1536` | lifecycle wrapper around one send turn | `AIBuilderPlanner.send_message` | moves | The caller should read as planner flow, not lock plumbing. |
| duplicated lease-lost event block | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1327-1339`, `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1356-1367` | caller-owned SSE error formatting | `AIBuilderPlanner.send_message` | stays in caller via local function | The prompt requires SSE formatting to stay with the caller; local function removes duplication and helps the send-message LOC gate without changing ownership. |
| `_dispatch_chained_server_action_after_commit` | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:775-896` | deterministic post-commit `confirm_requirements` transition | `AIBuilderPlanner` | stays | Must keep chained server action sequencing and two-commit behavior intact. |
| chained lease-loss mapping | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:1471-1485` | maps lease loss during chained `confirm_requirements` dispatch to SSE | currently missing explicit mapping | stays in caller with fix | Local verification shows the current `BadRequestException(code="session_send_lease_lost")` handler only wraps the first `run_planner_turn`; the chained call sits outside it. This slice will wrap/re-poll the chained path so lease loss still emits the same `session_send_lease_lost` SSE error. |
| `repo.commit_turn` | `backend/src/intric/flows/ai_builder/ai_builder_repo.py:973`, `backend/src/intric/flows/ai_builder/ai_builder_dispatcher.py:121-130` | canonical persistence/transaction boundary | `AIBuilderRepository`/dispatcher | stays | Explicitly preserved; the lock context manager must not own commits. |
| `run_planner_turn` | `backend/src/intric/flows/ai_builder/ai_builder_planner_turn.py:134-152` | planner pipeline/dispatcher bridge | `ai_builder_planner_turn.py` | stays | The planner-turn owner already exists; this slice does not recreate or move it. |
| `dispatch_planner_action` | `backend/src/intric/flows/ai_builder/ai_builder_dispatcher.py:121-130` | dispatch persistence via `commit_turn` | dispatcher | stays | Dispatch semantics and commit kwargs must remain unchanged. |

#### `PlannerTurnSendLock` Design

New module: `backend/src/intric/flows/ai_builder/ai_builder_planner_send_lock.py`.

Concrete constructor:

```python
PlannerTurnSendLock(
    *,
    repo: AIBuilderRepository,
    session_id: UUID,
    tenant_id: UUID,
    request_id: UUID,
    lease_seconds_now: Callable[[], int] = configured_send_lock_lease_seconds,
)
```

This intentionally differs from the starter prompt's `lease_seconds: int`
default. The current helper reads
`get_settings().ai_builder_send_lock_lease_seconds` every time lease seconds
are needed. Passing an `int` would snapshot the setting at construction and
silently change refresh-loop behavior. A callable preserves the current
call-time settings behavior and gives tests a deterministic seam without a fake
interface.
`configured_send_lock_lease_seconds` is a module-level callable in
`ai_builder_planner_send_lock.py`; only `PlannerTurnSendLock` calls it.

Public attributes:

- `lock_token: UUID`
- `lease_lost_event: asyncio.Event`

Private state:

- `_claimed`
- `_lease_lost`
- `_released`
- `_stop_event`
- `_lease_task`

Behavior:

- `__aenter__` calls `repo.claim_session_send(...)`.
- Failed claim raises `BadRequestException(code="session_message_in_progress")`
  with the current message text.
- Successful claim starts one background refresh task.
- The refresh task calls `repo.refresh_session_send_lease(...)` at the current
  refresh interval and sets `lease_lost_event` if refresh fails or returns
  false.
- `__aexit__` stops and awaits the refresh task, preserves caller
  cancellation/body exceptions, logs unexpected refresh-task errors, and
  releases through `repo.release_session_send(...)` only after a successful
  claim.
- If the body and refresh task both raise, the body exception wins and the
  refresh task error is logged.
- If `repo.release_session_send(...)` raises, that exception propagates just as
  the current outer `finally` does.
- The refresh task await must be cancellation-safe: `__aexit__` should stop the
  task and await cleanup without swallowing the caller's `CancelledError`.
- Release is idempotent and best-effort for a single context manager instance.
- `lease_lost_event` is single-use for one planner turn; the object is not
  reusable across turns.
- Re-entering the same `PlannerTurnSendLock` instance must raise before a
  second repository claim is attempted.
- Lease seconds are read from `lease_seconds_now()` at each claim/refresh
  operation. The default callable reads
  `get_settings().ai_builder_send_lock_lease_seconds`, preserving the current
  settings override behavior; do not cache settings across refresh ticks.

Implementation constraints:

- `ai_builder_planner_send_lock.py` stays at or below 150 LOC.
- Net production LOC must not increase.
- No `# noqa`, `type: ignore`, linter suppressions, Protocols, ABCs, factories,
  re-exports, or compatibility wrappers.
- `AIBuilderPlanner` must not retain delegating wrappers for moved helpers.

#### Behavior Pins Before Production Extraction

Add or update behavior tests before moving production code:

- `test_planner_send_lock_claims_refreshes_and_releases_once`
  - Protects claim, refresh, and release behavior on the new context manager.
- `test_planner_send_lock_failed_claim_raises_message_in_progress`
  - Protects concurrent send rejection through
    `BadRequestException(code="session_message_in_progress")`.
  - Also asserts `release_session_send` is not called when claim fails.
- `test_planner_send_lock_cancellation_releases_and_reraises`
  - Protects cancellation mid-pipeline: refresh task is stopped/awaited and
    the original cancellation is not swallowed.
- `test_planner_send_lock_body_exception_during_active_refresh_releases_and_reraises`
  - Protects arbitrary body exceptions: refresh task is stopped/awaited,
    release is called, and the original exception is re-raised unchanged.
- `test_planner_send_lock_refresh_false_sets_lease_lost`
  - Protects lease-lost state when refresh returns false.
- `test_planner_send_lock_refresh_exception_sets_lease_lost`
  - Protects lease-lost state when refresh raises.
- `test_planner_send_lock_reenter_raises_before_claim`
  - Protects the single-use context-manager invariant.
- `test_send_message_maps_lease_lost_from_planner_turn_to_sse`
  - Patch `run_planner_turn` to raise
    `BadRequestException(code="session_send_lease_lost")`, representing a lease
    CAS loss inside planner pipeline persistence or repair-loop persistence.
    Expected behavior: emit the existing `session_send_lease_lost` error SSE
    and `done`; do not leak the exception out of the generator.
- Add a focused `send_message` test for lease loss during the chained
  `architecture_committed` -> `confirm_requirements` call. This test must
  exercise the repository CAS failure path by making the second
  `repo.commit_turn(...)` call raise
  `BadRequestException(code="session_send_lease_lost")`. Expected behavior:
  emit `status` for `architecture_committed`, then emit the same
  `session_send_lease_lost` error SSE and `done`; do not leak the
  `BadRequestException` out of the generator.
- Re-poll `PlannerTurnSendLock.lease_lost_event` after the chained call as well
  as after the first planner turn. Expected behavior: if the lease is lost after
  the chained commit returns but before the caller emits
  `requirements_summary`, emit the existing `session_send_lease_lost` error SSE
  and `done` instead of a stale summary.
- Rename the body-exception pin to
  `test_planner_send_lock_body_exception_during_active_refresh_releases_and_reraises`
  and make the test exercise an active refresh task, not only an idle context.

#### Preservation Requirements

Do not change:

- `backend/src/intric/flows/ai_builder/ai_builder_planner_turn.py`
- `run_planner_turn` semantics
- `dispatch_planner_action` semantics
- `repo.commit_turn` as canonical persistence/transaction boundary
- prompt-contract anchors
- proposal processing behavior
- edit proposal behavior
- repair retry behavior
- router/SSE event names, order, or payload shape
- audit metadata behavior
- frontend behavior

The chained post-commit server action must remain intact:

`architecture_committed` -> chained `confirm_requirements` -> `requirements_summary`

The chained path must still:

- run under the same send lock / lease
- pass the same outer `request_uuid` and `lock_token` into the chained
  `run_planner_turn` call
- call `commit_turn` twice where today it does
- preserve monotonically increasing `planning_state_version`
- emit the same expected `requirements_summary` SSE event exactly once
- map lease loss during the chained dispatch to the same
  `session_send_lease_lost` SSE error instead of propagating
  `BadRequestException`
- re-poll `lease_lost_event` after the chained call before emitting
  `requirements_summary`

#### Validation Commands

Docker/container discovery:

```bash
docker ps --format '{{.Names}}'
```

Local fallback validation, because Docker is blocked in this session:

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py -q
```

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_planner.py tests/unittests/flows/ai_builder/test_ai_builder_planner_turn.py tests/unittests/flows/ai_builder/test_ai_builder_dispatcher.py -q
```

```bash
cd backend && uv run pytest tests/integration/flows/test_ai_builder_session_api_regressions.py tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py tests/integration/flows/test_ai_builder_edit_apply_regressions.py -q
```

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_repair.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_router.py -q
```

```bash
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_planner.py src/intric/flows/ai_builder/ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py tests/unittests/flows/ai_builder/test_ai_builder_planner.py
```

```bash
cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_planner.py src/intric/flows/ai_builder/ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py tests/unittests/flows/ai_builder/test_ai_builder_planner.py
```

```bash
cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_planner.py src/intric/flows/ai_builder/ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_lock.py tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py tests/unittests/flows/ai_builder/test_ai_builder_planner.py
```

```bash
cd backend && uv run lint-imports --no-cache
```

```bash
git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_planner.py backend/src/intric/flows/ai_builder/ai_builder_planner_send_lock.py backend/tests/unittests/flows/ai_builder/test_ai_builder_planner_send_lock.py backend/tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py backend/tests/unittests/flows/ai_builder/test_ai_builder_planner.py docs/refactor/execution/batch-6-ai-builder-contract-split
```

Committed-text hygiene guard:

```bash
rg -n "A\.0|A\.6|P0\.|Phase 0-G|§A\.|plan §|/tmp/ai_builder_|plan/phases|sectioned intake slice|planner send-lock slice|Batch 6|6d" \
  backend/src backend/tests docs/refactor/prd docs/refactor/ai-builder-prompt-contract.md
```

Expected: no matches in committed source/tests/prompt-contract docs. Process
artifact references under this batch directory are allowed.

#### Expected Files To Change

Source:

- `backend/src/intric/flows/ai_builder/ai_builder_planner.py`
- `backend/src/intric/flows/ai_builder/ai_builder_planner_send_lock.py`

Tests:

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_planner_send_lock.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_planner.py` only if
  import/path adjustments are required by the extraction

Docs/process:

- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/retrospective-4.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-4.md`

Do not touch:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`
- `backend/src/intric/flows/ai_builder/ai_builder_planner_turn.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py`
- `backend/src/intric/flows/ai_builder/ai_builder_repair.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py`
- `backend/src/intric/flows/ai_builder/ai_builder_router.py`
- frontend files
- migrations

#### Carry-Forward Risks

- Router/presenter thinning remains a later Batch 6 slice.
- Frontend AI Builder protocol alias work remains a later Batch 6 slice.
- `ai_builder_models.py` star-barrel migration remains deferred until AI Builder
  owners are clearer.
- Package and namespace renames remain out of scope.

## Archive - Create/Edit Proposal Processing Separation (Committed At af898af4)

Outcome: shipped in `af898af4 flows: separate ai builder edit proposal
processing`. Edit argument processing, description repair, edit retry config,
and provenance parsing moved into `ai_builder_edit_proposal.py`; create
processing and shared proposal orchestration stayed in
`ai_builder_proposal_processor.py`.

Carry-forward from that checkpoint: `_handle_edit_flow` deliberately stayed in
the processor spine because event streaming and self-correction retry
orchestration are shared. This remains part of the broader PRD-005
create/edit/repair separation status, not a compatibility path.

### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=8` | latest commit is `fd5b725b flows: harden ai builder repair retry contract` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; dirty files limited to `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, `PRODUCT.md` plus this plan draft |
| `git diff --cached --name-only` | no staged files |
| Docker check | `docker ps --format '{{.Names}}'` blocked by host execution policy; local fallback validation planned |

Known unrelated dirty files are out of scope and must remain untouched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

This narrow slice separates edit proposal processing from create proposal
processing without changing proposal contracts, repair budgets, router behavior,
SSE events, audit behavior, frontend state, or prompt anchors.

PRD-005 constraints that govern this slice:

- "No fake one-method interfaces are introduced."
- "no interface unless two real implementations exist."

Default structural decision:

- Add one production module:
  `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py`.
- Keep the module stateless and function-based.
- Keep create behavior, shared submission orchestration, shared typed
  contracts, usage tracking, retry orchestration, and dispatch in
  `ai_builder_proposal_processor.py`.
- Move only edit-specific processing functions when their dependency surface is
  edit-domain or processor-owned state can be passed explicitly without hiding
  required callback arguments inside retry `process_tool_kwargs`.
- Do not create shared/base/common/types/contracts modules.
- Do not create classes, Protocols, ABCs, adapters, inheritance, or
  package-level re-exports.

### Required Pre-Diff Inventory Command

This command ran before any production diff:

```bash
git grep -n "AIBuilderProposalProcessor\|_process_edit_arguments\|_handle_edit_flow\|_attempt_description_repair\|_edit_flow_retry_config\|_handle_submission_tool_call\|_dispatch_known_tool_call\|EDIT_FLOW_TOOL_NAME" -- backend/src backend/tests
```

Key result:

- `AIBuilderProposalProcessor` is owned by
  `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:417`.
- Edit tool dispatch currently enters `_handle_edit_flow` at
  `ai_builder_proposal_processor.py:1089-1116`.
- Shared submission orchestration is `_handle_submission_tool_call` at
  `ai_builder_proposal_processor.py:1210-1316`.
- Candidate edit-only methods live at
  `ai_builder_proposal_processor.py:2054-2314`,
  `ai_builder_proposal_processor.py:2386-2438`,
  `ai_builder_proposal_processor.py:2440-2493`, and
  `ai_builder_proposal_processor.py:2592-2609`.
- Existing tests directly call or patch edit methods in
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1276-2029`
  and `backend/tests/unit/test_ai_builder_plan_edit_context.py:561`.

### Inventory And Movement Decisions

| name | file:line | column (create-only / edit-only / shared spine) | decision (stays / moves to ai_builder_edit_proposal.py) | reason |
|---|---|---|---|---|
| `ToolProcessingResult` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:295-309` | shared spine | stays | Frozen contract named by the prompt; both create and edit processing return it. The edit module may import it function-locally only where constructing results. |
| `ProposalUsageTracker` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:316-369` | shared spine | stays | Proposal-level telemetry spans create/edit and repair calls. Moving it would widen scope and create a false edit owner. |
| `ProposalContext` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:372-395` | shared spine | stays | Dispatch context is shared by all tool handlers and explicitly frozen for this slice. |
| `SubmissionToolHandlerConfig` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:398-406` | shared spine | stays | Shared submission handler owns parse/self-correction plumbing for outline submission. |
| `ToolRetryConfig` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:409-414` | shared spine | stays | Shared retry orchestration consumes this contract. The edit module may import it function-locally only where constructing retry configs. |
| `MAX_SELF_CORRECTION_RETRIES` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:172` | shared spine | stays | Numeric retry budget is frozen and must not move or change. |
| `_format_quality_feedback` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:437-447` | shared spine | stays | Used by both create and edit paths. If moved across module boundaries, drop the underscore to make the processor-spine contract explicit instead of suppressing pyright. |
| `_format_contextual_quality_feedback` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:449-464` | shared spine | stays | Used by both create and edit paths and depends on processor-owned warning policy. If moved across module boundaries, drop the underscore to make the processor-spine contract explicit. |
| `_process_outline_arguments` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:466-564` | create-only | stays | Create behavior remains in the existing processor as required. |
| `_process_create_draft` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:566-781` | create-only | stays | Create responsibility is not moved in this slice. |
| `_mcp_clarification_events_if_needed` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:783-844` | shared spine | stays | Both create/edit processing need this policy and it persists backend questions through processor-owned repo/user state. If moved across module boundaries, drop the underscore to make the processor-spine contract explicit. |
| `_build_self_correction_error_event` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:846-870` | shared spine | stays | Error-event mapping is retry/SSE behavior, not edit proposal compilation. |
| `handle_tool_call` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:872-931` | shared spine | stays | Owns suppression of raw planner text and dispatch across all tool types. |
| `propose_plan` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:933-1087` | shared spine | stays | Owns LLM proposal call and active tool selection. Planner-turn extraction is forbidden. |
| `_dispatch_known_tool_call` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1089-1116` | shared spine | stays | Shared dispatcher remains in the processor. It can delegate edit handling to the edit module without moving dispatch ownership. |
| `_mcp_preflight_events_if_needed` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1118-1169` | shared spine | stays | Preflight MCP question behavior is proposal-wide. |
| `_resolve_submission_prerequisite_events` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1171-1208` | shared spine | stays | Requirements/discovery gate applies before proposal submission and is not edit-specific. |
| `_handle_submission_tool_call` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1210-1316` | shared spine | stays | Existing outline submission wrapper stays. Moving it would mix create/edit separation with submission orchestration. |
| `_build_submission_processing_kwargs` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1318-1352` | shared spine | stays | Shared helper for submission processing arguments. |
| `_handle_outline_flow_tool_call` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1354-1376` | create-only | stays | Outline flow remains in create processor. |
| `_call_repair_completion` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1378` | shared spine | stays | Shared LLM repair completion boundary; moving it would start repair/planner extraction. If moved across module boundaries, drop the underscore to make the processor-spine contract explicit. |
| `_process_confirm_requirements_arguments` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:1965` | shared spine | stays | Requirements confirmation is neither create nor edit proposal processing. |
| `_process_edit_arguments` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2054-2314` | edit-only | moves to ai_builder_edit_proposal.py | This is the largest edit-specific responsibility: parse edit draft, normalize/validate/compile edit operations, repair description, apply edit quality policy, and persist edit plan. Retry callables will bind `processor` with a typed local binding function so retry `process_tool_kwargs` keep the current shape. |
| `_handle_confirm_requirements` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2316-2384` | shared spine | stays | Confirmation flow is outside edit proposal processing. |
| `_handle_edit_flow` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2386-2438` | edit-only adapter | stays for this slice | It is edit-specific but tightly coupled to shared self-correction event streaming and `ProposalContext`. Moving it would require either a callback-heavy leaf or broader retry ownership changes. It will delegate edit argument processing to the new module. |
| `_attempt_description_repair` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2440-2493` | edit-only | moves to ai_builder_edit_proposal.py | Description-only repair is part of edit proposal processing and uses existing edit-domain invariance helpers. |
| `emit_discovery_followup_if_needed` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2495-2523` | shared spine | stays | Proposal-wide discovery follow-up adapter; moving would widen the slice. |
| `_submission_retry_config` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2525-2574` | shared spine | stays | Shared forced proposal retry config chooses create vs edit based on flow context. The edit branch will point at the edit module function. |
| `_confirm_requirements_retry_config` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2576-2590` | shared spine | stays | Confirmation retry config is unrelated to edit proposal processing. |
| `_edit_flow_retry_config` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2592-2609` | edit-only | moves to ai_builder_edit_proposal.py | Builds edit-specific retry config and can stay as a stateless leaf function with a function-local `ToolRetryConfig` import and a typed bound edit callable. |
| `_extract_description_provenance` | `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:2612` | edit-only | moves to ai_builder_edit_proposal.py | Used only by edit description repair eligibility. Keep it private inside the new module because it is not a cross-module contract. |
| `EDIT_FLOW_TOOL_NAME` | `backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py:28` | edit-only | stays in existing edit-domain module | Canonical tool-name owner already exists. No re-export or rename. |
| `strip_malformed_edit_mechanics` | `backend/src/intric/flows/ai_builder/ai_builder_edit_normalizer.py:31-65` | edit-only | stays | Existing edit normalizer is the canonical owner. The new module imports it. |
| `normalize_edit_draft_mechanics` | `backend/src/intric/flows/ai_builder/ai_builder_edit_normalizer.py:68-100` | edit-only | stays | Existing edit normalizer is the canonical owner. |
| `validate_edit_draft` | `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py:36-80` | edit-only | stays | Existing edit validator is the canonical owner. |
| `compile_edit_draft` | `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py:65-105` | edit-only | stays | Existing edit compiler is the canonical owner. |
| `should_attempt_description_repair` | `backend/src/intric/flows/ai_builder/ai_builder_edit_repair.py:18-44` | edit-only | stays | Existing repair eligibility owner. The new module imports it. |
| `validate_repair_invariance` | `backend/src/intric/flows/ai_builder/ai_builder_edit_repair.py:47-57` | edit-only | stays | Existing repair invariant owner. The new module imports it. |

### Edit Module Design

`ai_builder_edit_proposal.py` will contain module-level functions only:

- `process_edit_arguments`
- `attempt_description_repair`
- `_bind_process_edit_arguments`
- `edit_flow_retry_config`
- `_extract_description_provenance`

Boundary rule: dispatch, event streaming, and retry orchestration stay in the
processor spine; edit-domain composition moves to the edit proposal module.
The processor may top-level import `process_edit_arguments` and
`edit_flow_retry_config` because the edit module imports `AIBuilderProposalProcessor`
only under `TYPE_CHECKING`.

The module must:

- use `from __future__ import annotations`
- use `TYPE_CHECKING` imports for annotation-only types
- import edit-domain modules at top level only from existing edit owners:
  `ai_builder_edit_repair.py`, `ai_builder_edit_models.py`,
  `ai_builder_edit_compiler.py`, `ai_builder_edit_normalizer.py`,
  `ai_builder_edit_validator.py`, and `ai_builder_edit_tool_schema.py`
- use function-local imports for frozen contracts from
  `ai_builder_proposal_processor.py` only where those contracts are constructed
- keep function-local frozen-contract imports in at most three leaf functions
- avoid lint suppressions, `type: ignore`, `# noqa`, package re-exports, and
  compatibility shims
- bind `process_edit_arguments` with a tiny typed binding function when
  constructing retry configs so `process_tool_kwargs` does not gain a hidden
  required `processor` field and signature filtering still sees `flow` and
  `assistant_metadata`
- keep dispatchers/event streaming/retry orchestration in the processor spine
  and move edit-domain composition only; this is the boundary rule for this
  slice

The main leaf signature will be keyword-only and stateless:

```python
async def process_edit_arguments(
    *,
    processor: AIBuilderProposalProcessor,
    session_id: UUID,
    conversation: list[ConversationMessage],
    ...
) -> ToolProcessingResult:
    ...
```

`processor` is required because this slice deliberately keeps repo/user
persistence, MCP clarification, quality feedback, and repair completion
ownership in the existing processor instead of creating a new service/class.
Direct callers must pass `processor=processor`. Retry callers must use a
bound callable so `ai_builder_proposal_repair.py` signature filtering sees the
same external callback shape as today's bound method.

Cross-module calls to processor-spine operations must use explicit public
internal methods, not private-method access or pyright suppressions. If the edit
module begins needing more processor-spine methods, stop and re-plan instead of
adding more reach-back.

### Deferred Movement

`_handle_edit_flow` stays in `ai_builder_proposal_processor.py` for now.
Evidence:

- it parses tool-call JSON and delegates shared self-correction through
  `_request_tool_self_correction` at
  `ai_builder_proposal_processor.py:2386-2438`
- the self-correction retry path is shared across outline, confirmation, and
  edit and is not an edit proposal compilation responsibility
- moving it would force callback plumbing into the leaf module or move shared
  retry ownership, which violates the maximum-one-module and narrow-slice
  budget

This is not a compatibility path. It is a boundary decision: event streaming and
retry orchestration remain in the processor spine, while edit argument
processing moves to the edit leaf.

### Preserved Behavior Pins

These pins must remain green:

- prompt-contract artifact: `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py:12`
- proposal repair retry tests:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py:162`
- semantic/parse repair tests:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_repair.py:93`
  and `backend/tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py:207`
- router SSE done/error order tests:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1185`,
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1250`,
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1281`,
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1525`,
  and `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1562`
- router audit metadata tests:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:383`,
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:851`,
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1620`,
  and `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1715`
- create/revise/approve/apply integration regressions:
  `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py:2424`
- edit/apply integration regressions:
  `backend/tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py:88`
  and `backend/tests/integration/flows/test_ai_builder_edit_apply_regressions.py:1`
- edit processing unit pins:
  `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py:1276-2029`
  and `backend/tests/unit/test_ai_builder_plan_edit_context.py:561`

### Test Strategy

Keep tests co-located in
`backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`.
There are direct edit-only tests, but moving them now would make the diff harder
to review and would mostly protect file location rather than behavior. Update
patch paths and calls so existing tests continue to protect:

- contextual quality feedback
- MCP clarification and policy feedback
- edit metadata propagation into the validator
- mechanical ref normalization before validation
- text suppression around submission tool calls
- typed edit retry config
- parse failure self-correction behavior

No tests should assert private helper calls merely to protect the refactor.

Explicit test call-site updates:

- `test_ai_builder_proposal_processor.py:1334`,
  `test_ai_builder_proposal_processor.py:1421`,
  `test_ai_builder_proposal_processor.py:1518`,
  `test_ai_builder_proposal_processor.py:1616`, and
  `test_ai_builder_proposal_processor.py:1716` switch from
  `processor._process_edit_arguments(...)` to
  `process_edit_arguments(processor=processor, ...)`.
- `test_ai_builder_plan_edit_context.py:561` makes the same direct-call update.
- `test_ai_builder_proposal_processor.py:1946` stops asserting callable
  identity against a private bound method. It should assert behavior-level
  retry-config shape, target tool name, forced prompt, unchanged
  `process_tool_kwargs`, and, if needed, that the callable is invokable through
  the public retry path.
- Patch paths for edit compilation/validation/preparation/storage move from
  `ai_builder_proposal_processor` to `ai_builder_edit_proposal` only when the
  patched function moved.
- Add or update a stable-substring pin for the description-only edit repair
  prompt. This prompt is an LLM repair contract surface and must keep anchors
  such as `Generate ONLY a new flow_description` and
  `Respond with ONLY the new description text`. Both anchors must map to
  `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py` in the
  prompt-contract artifact test.

### Expected Files To Change

Production:

- `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`

Tests:

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
- `backend/tests/unit/test_ai_builder_plan_edit_context.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`

Process artifacts:

- `docs/refactor/ai-builder-prompt-contract.md` only to add the description
  repair contract paragraph and anchors, not to weaken existing anchors
- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- next numbered retrospective and Claude reconciliation files

No frontend files, router files, planner files, prompt-contract docs, PRDs, or
known unrelated dirty files are expected to change.

### Validation Commands

Targeted proposal processor and edit-context tests:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unit/test_ai_builder_plan_edit_context.py \
  -q
```

Prompt-contract artifact test:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  -q
```

Repair and parse-repair tests:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  -q
```

Router SSE and audit tests:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  -q
```

Create/revise/approve/apply integration regressions:

```bash
cd backend && uv run pytest \
  tests/integration/flows/test_ai_builder_session_api_regressions.py \
  -q
```

Edit/apply integration regressions:

```bash
cd backend && uv run pytest \
  tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py \
  tests/integration/flows/test_ai_builder_edit_apply_regressions.py \
  -q
```

Targeted pyright:

```bash
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_edit_proposal.py \
  src/intric/flows/ai_builder/ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unit/test_ai_builder_plan_edit_context.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py
```

Targeted ruff:

```bash
cd backend && uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_edit_proposal.py \
  src/intric/flows/ai_builder/ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unit/test_ai_builder_plan_edit_context.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py
```

Targeted format check:

```bash
cd backend && uv run ruff format --check \
  src/intric/flows/ai_builder/ai_builder_edit_proposal.py \
  src/intric/flows/ai_builder/ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unit/test_ai_builder_plan_edit_context.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py
```

Import boundaries:

```bash
cd backend && uv run lint-imports --no-cache
```

Diff hygiene:

```bash
git diff --check -- \
  backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py \
  backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  backend/tests/unit/test_ai_builder_plan_edit_context.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  docs/refactor/ai-builder-prompt-contract.md \
  docs/refactor/execution/batch-6-ai-builder-contract-split
```

Committed-text hygiene, excluding process artifacts:

```bash
rg -n "6c|Batch 6|create/edit split|proposal split|edit carve-out|leaf module" \
  backend/src backend/tests docs/refactor/prd docs/refactor/ai-builder-prompt-contract.md
```

Expected: no matches.

Frontend AI Builder tests are not run because this slice forbids frontend edits
and does not touch frontend protocol/event surfaces. If validation or Claude
finds a frontend-facing contract risk, stop and ask for a scope decision.

### Claude Plan Review

Before implementation, run Claude peer-loop against this plan and ask whether
moving only edit argument processing, description repair, retry-config creation,
and description provenance into a stateless edit module is cleaner than moving
`_handle_edit_flow` too. Specific questions:

- Does the proposed boundary improve ownership or merely move lines?
- Is leaving `_handle_edit_flow` in the shared processor spine defensible?
- Does the required `processor` parameter create a worse dependency than the
  current method location?
- Are there import-cycle or import-linter risks?
- Are any tests overfitted to private helper location?

Do not implement until the plan has green light or a documented,
evidence-backed disagreement.

## Archive - Prompt/Audit Contract Checkpoint (Committed At 4cd874c7)

### Archived Start Gate

| Check | Result |
|---|---|
| `git rev-parse --short HEAD` | `546d472c` |
| Latest commit | `flows: align frontend flow types with generated schemas` |
| Staged files | none |
| Dirty files | `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, `PRODUCT.md` |
| Docker check | `docker ps --format '{{.Names}}'` was blocked by host execution policy before execution |

Known dirty files are out of scope and must remain untouched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Archived Scope Decision

Batch 6 is PRD-005 AI Builder contract split. This session implements only:

#### 6a - Behavior Pins And Prompt-Contract Audit

Allowed:

- `docs/refactor/ai-builder-prompt-contract.md`
- behavior tests for create, revise, approve, apply
- SSE event order/error tests
- prompt assembly obligation tests
- repair-policy obligation tests
- knowledge-pack rule fixtures where stable
- batch journal, plan, retrospective, and Claude reconciliation docs

Forbidden in 6a:

- structural production refactors in `backend/src/intric/flows/ai_builder/*.py`
- router thinning
- module splitting
- frontend state-owner edits
- generated client regeneration
- `@intric/intric-js` package rename
- `intric.*` to `eneo.*` package/module/import rename

Stop after 6a reaches the commit boundary.

### Archived Source-Of-Truth Owners

| Concept | Current owner | Evidence | 6a action |
|---|---|---|---|
| HTTP endpoints, response models, SSE adapter, route-level audit | `backend/src/intric/flows/ai_builder/ai_builder_router.py` | create session audit at lines 320-369; SSE wrapper and done/error handling at lines 475-617; approve/apply/revise endpoints at lines 931-1134 | Pin behavior only; do not move code in 6a |
| Session creation and planner/service composition | `backend/src/intric/flows/ai_builder/ai_builder_service.py` | `AIBuilderService.create_session` lines 187-232; `send_message` lines 459-500; `approve_plan`/`apply_plan`/`revise_plan` lines 548-626 | Pin endpoint behavior around service outcomes; do not split service in 6a |
| Planner prompt assembly | `backend/src/intric/flows/ai_builder/ai_builder_prompts.py` | `build_system_prompt` lines 84-132; context/knowledge/model/MCP sections lines 153-222; clarification hints lines 271-485 | Add contract docs and targeted prompt obligation pins |
| Prompt knowledge-pack protocol | `ai_builder_knowledge_pack.py`, `ai_builder_knowledge_pack_protocol.py`, `ai_builder_knowledge_pack_core.py`, `ai_builder_knowledge_pack_edit.py` | protocol mandates `outline_flow`/`edit_flow`, no plan proposals in planner JSON, required action payload fields, and server-derived architecture commit | Add/extend knowledge-pack tests where stable |
| SSE payload builders | `backend/src/intric/flows/ai_builder/ai_builder_events.py`, `ai_builder_event_models.py` | event names and error payloads at `ai_builder_events.py` lines 22-159; models at `ai_builder_event_models.py` lines 14-62 | Pin done/error ordering and error payload shape |
| Active semantic/parse repair | `backend/src/intric/flows/ai_builder/ai_builder_repair.py` | repair eligibility and typed outcomes at lines 90-536 | Document and pin obligations; no deletion |
| Active proposal/tool repair | `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py`, `ai_builder_repair_transport.py` | retry budget, forced tool retry, JSON text fallback, error event behavior at `ai_builder_proposal_repair.py` lines 127-584 | Document and pin obligations; no deletion |
| Edit-specific description repair | `backend/src/intric/flows/ai_builder/ai_builder_edit_repair.py` | description-only invariance checks at lines 18-57 | Inventory for 6b; no movement in 6a |
| Generated frontend schema source | `frontend/packages/intric-js/src/types/schema.d.ts` | AI Builder paths at lines 4152-4369; schemas at lines 8730, 10399, 16334, 16349, 16685, 16920, 17162, 17226, 17332 | Planning evidence only in 6a |
| Manual frontend protocol blocks | `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts` and `structuredQuestionAnswer.ts` | manual event/session/plan/status types at `protocol.ts` lines 4-240; structured question types in `structuredQuestionAnswer.ts` | No frontend edits in 6a; map for 6f only |

### Archived AI Builder File Inventory

6a uses the AI Builder package as read-only evidence and changes only tests/docs. Full ownership movement is intentionally deferred to the later slice that owns that code path.

| Area | Evidence files | 6a action | Later owner slice |
|---|---|---|---|
| HTTP/SSE/audit adapter | `ai_builder_router.py`, `ai_builder_events.py`, `ai_builder_event_models.py` | Strengthen behavior pins only | 6e |
| Service/session composition | `ai_builder_service.py`, `ai_builder_session_transitions.py`, `ai_builder_plan_lifecycle.py` | Read-only evidence | 6d/6e |
| Prompt assembly and knowledge pack | `ai_builder_prompts.py`, `ai_builder_knowledge_pack*.py`, `ai_builder_tools.py`, `ai_builder_action_policy.py` | Prompt-contract doc plus prompt/knowledge-pack pins | 6d |
| Create/edit proposal processing | `ai_builder_create_*.py`, `ai_builder_edit_*.py`, `ai_builder_proposal_processor.py`, `ai_builder_materializer.py` | Read-only evidence | 6c |
| Repair and validation | `ai_builder_repair.py`, `ai_builder_proposal_repair.py`, `ai_builder_repair_transport.py`, `ai_builder_validation_*.py`, `ai_builder_validator.py` | Repair obligation pins only | 6b |
| Planner turn orchestration | `ai_builder_planner.py`, `ai_builder_planner_turn.py`, `ai_builder_orchestration_pipeline.py`, `ai_builder_dispatcher.py`, `planning_state*.py` | Read-only evidence | 6d |
| Frontend protocol surface | `frontend/packages/intric-js/src/types/schema.d.ts`, `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts`, `structuredQuestionAnswer.ts` | Inventory only; no edits | 6f |

### Archived Sliced Batch Plan

| Slice | Goal | Production code edits? | Stop gate |
|---|---|---:|---|
| 6a | Behavior pins and prompt-contract audit | No | commit boundary after tests/docs only |
| 6b | Repair policy classification and extraction | Yes, only after repair inventory | user approval after 6a |
| 6c | Split create vs edit proposal processing | Yes, no fake one-method interfaces | after 6b |
| 6d | Planner turn use case | Yes, define lock, prompt, LLM, mutation, persistence, rollback, telemetry boundaries | after 6c |
| 6e | Thin router and presenter | Yes, move response shaping/use-case behavior only where owner is clear | after 6d |
| 6f | Frontend protocol aliases only | Type-only frontend changes; no Driver/Service state refactor | after backend contract is stable |

If 6a cannot stay test/docs-only, stop and ask to split the batch further.

### Archived Behavior Pins Before Refactors

Existing coverage is already stronger than the initial 6a plan assumed. 6a therefore adds a bounded coverage delta instead of duplicating broad integration tests.

Audit metadata deltas should modify the existing router audit tests. Use a small local assertion helper only if it makes the test diff easier to read; do not add parallel audit test methods for the same event.

| Behavior | Existing pin | 6a delta |
|---|---|---|
| Create session audit | `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:351-374` asserts `AI_BUILDER_SESSION_CREATED` action/entity | Strengthen the router unit test to assert tenant id, actor id, actor metadata, target metadata, target kind, and flow id when present |
| Cancel session audit | `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:796-821` asserts audit call | Strengthen the router unit test to assert action/entity, tenant id, actor id, actor metadata, target metadata, and target kind |
| Approve plan audit | `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1557-1581` asserts `AI_BUILDER_PLAN_APPROVED` action/entity | Strengthen the router unit test to assert tenant id, actor id, actor metadata, plan target metadata, and `plan_id` extra metadata |
| Apply plan audit | `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1637-1669` asserts `AI_BUILDER_FLOW_APPLIED` action/entity | Strengthen the router unit test to assert tenant id, actor id, flow target metadata, `plan_id`, and created/updated/removed step counts |
| Revise plan behavior | `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py:1750-1798` covers revise success and service error translation | Keep existing router pin in validation; do not broaden unless a concrete revise contract gap appears |
| SSE terminal ordering | `test_ai_builder_router.py:1097-1244` asserts usage-before-done/done behavior; `test_ai_builder_router.py:1463-1530` asserts error-then-done for generic and bad-request errors | No new SSE test unless implementation work exposes a concrete gap; keep router unit tests in validation |
| Prompt assembly obligations | `test_ai_builder_prompts.py` covers prompt sections and action vocabulary; `test_ai_builder_knowledge_pack.py` covers knowledge-pack protocol fixtures | Add prompt-contract artifact linkage so the durable doc and prompt obligation anchors cannot silently drift |
| Knowledge-pack protocol | `test_ai_builder_knowledge_pack.py` covers `outline_flow`/`edit_flow`, action fields, and server-derived architecture commit obligations | No broad fixture expansion in 6a unless the prompt-contract linkage exposes a missing anchor |
| Semantic and parse repair | `test_ai_builder_repair.py:145-165` verifies semantic repair detail is not raw code; `test_ai_builder_proposal_repair.py:162-191` pins proposal retry budget | Add parse-repair budget and raw JSON instruction pins if not already covered |
| Proposal repair failure shape | `test_ai_builder_proposal_repair.py` covers repair failure/event behavior; `test_ai_builder_failure_events.py` covers planner failure event payloads | Keep in validation; do not add failure-event tests unless a concrete unpinned failure shape is found |
| Create/approve/apply happy paths | `test_ai_builder_session_api_regressions.py:2424-2735` covers create, approve, apply, and edit-output-only apply behavior | Keep existing integration pins in validation; no audit assertions here because audit is injected at router seam |
| Structured question and open-flow/resume flow | `test_ai_builder_session_api_regressions.py:2071-2418`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilder.test.ts:15-50`, and `FlowAIBuilderDriver.test.ts:102-411` cover structured-question and resume behavior | No 6a edits; frontend protocol aliasing is deferred to 6f |

### Archived Prompt Contract Artifact Plan

Create `docs/refactor/ai-builder-prompt-contract.md` with:

- canonical prompt assembly owner and caller boundaries
- prompt inputs:
  - mode (`create` vs `edit`)
  - flow context
  - available models
  - available knowledge bases
  - available MCP servers/tools
  - confirmed requirements
  - action policy
  - UI language
  - planner hints
- required LLM obligations:
  - use planner JSON action vocabulary
  - do not emit plan proposals inside planner JSON
  - call `outline_flow` in create mode and `edit_flow` in edit mode for final proposals
  - use exact `ref` values for knowledge/MCP references
  - keep `architecture_commit` server-derived where required
  - respect ask-question payload vocabulary
- repair-policy obligations:
  - semantic repair does not render raw rejection codes into prompts
  - parse repair is separate from semantic repair
  - proposal tool repair preserves tool-call grouping and retry budget
  - repair failures emit typed client-safe errors and log sanitized diagnostics
- test ownership:
  - prompt/knowledge-pack unit tests own prompt text obligations
  - repair unit tests own repair budgets and failure shape
  - API integration tests own create/revise/approve/apply and SSE behavior

Add one test linkage so the artifact is not decorative:

- A prompt-contract artifact test must read `docs/refactor/ai-builder-prompt-contract.md`.
- The test must assert a small set of durable obligation anchors appear in both the artifact and the relevant prompt/protocol owner:
  - `base_planning_state_version`
  - `outline_flow`
  - `edit_flow`
  - exact knowledge/MCP `ref` values
  - server-derived `architecture_commit`
  - raw JSON parse repair instructions
- Use exact substring matching for these anchors. The linkage must stay focused on stable contract anchors, not full prompt snapshots.

### Archived Repair Policy Inventory

| Repair surface | Owner file | Active LLM boundary | Stale compatibility | Unknown | 6a action |
|---|---|---:|---:|---:|---|
| Semantic planner rejection repair | `ai_builder_repair.py` | yes | no | no | document and test obligations |
| Planner parse repair | `ai_builder_repair.py` | yes | no | no | document and test obligations |
| Proposal self-correction | `ai_builder_proposal_repair.py` | yes | no | no | document and test obligations |
| Forced tool retry after conversational text | `ai_builder_proposal_repair.py` | yes | no | no | document and test obligations |
| JSON text fallback during forced retry | `ai_builder_proposal_repair.py` | yes | no | no | classify as active proposal repair; document and do not delete in 6a |
| Repair transport persistence | `ai_builder_repair_transport.py` | no, but persists active LLM repair turns | no | no | document and test obligations |
| Edit description-only repair | `ai_builder_edit_repair.py` | no direct LLM call in helper | no | no | inventory for 6b |
| Planner output normalization | `ai_builder_planner_output_normalizer.py` | no direct LLM call | no | no | classify as active server-owned normalization before guardrail evaluation; do not delete in 6a |

### Archived Router Thinning Plan For Later

| Router helper/endpoint | 6a action | Later owner candidate | Reason |
|---|---|---|---|
| `_authorize_ai_builder_request` | read-only | router/auth adapter | HTTP/auth concern stays in router boundary |
| `_ai_builder_error_response` | read-only | presenter or API model helper | response example shaping can move only after OpenAPI pins |
| `_to_session_response`, `_to_plan_response` | read-only | presenter | response shaping candidate for 6e |
| `send_message` SSE wrapper | test only | router + presenter/use case split | HTTP stream and terminal event ordering must stay explicit |
| `create_session` audit | test only | possibly application use case later | 6a pins current audit metadata before any move |
| `approve_plan` and `apply_plan` audit | test only | possibly plan lifecycle/use case later | 6a pins current audit metadata before any move |
| `revise_plan` | test only | proposal/edit use case later | 6c/6e can split after behavior pins |

### Archived Frontend Protocol Type Scope

6a does not edit frontend protocol types. 6f may later map these generated schemas:

| Generated schema | Evidence | Manual frontend block |
|---|---|---|
| `CreateSessionRequest` | `schema.d.ts:10399-10406` | `AIBuilderSession` creation request usage in `FlowAIBuilderDriver.ts` |
| `SessionResponse` | `schema.d.ts:17332-17360` | `AIBuilderSession` in `protocol.ts:66-80` |
| `SessionListResponse` | `schema.d.ts:17162-17180` | `AIBuilderDraftSession` and draft list state |
| `SessionModelsResponse` | `schema.d.ts:17226-17240` | `AIBuilderModel` in `protocol.ts:214-220` |
| `PlanResponse` | `schema.d.ts:16349-16424` | `ProposedPlan` and plan fields in `protocol.ts` |
| `PlanApprovalResponse` | `schema.d.ts:16334-16346` | approve response handling in `FlowAIBuilderDriver.ts` |
| `ApplyPlanRequest` | `schema.d.ts:8730-8735` | `applyPlan(expectedRevision)` transport call |
| `ApplyResultResponse` | `schema.d.ts:8740-8749` | `ApplyResult` manual block |
| `RevisePlanRequest` | `schema.d.ts:16685-16690` | `PlanRevisionType` and revise call |
| `SendMessageRequest` | `schema.d.ts:16920-16939` | message payload and `AIBuilderPlanEditContext` |

Manual protocol blocks observed:

- `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:4-240`
- `frontend/apps/web/src/lib/features/flows/ai-builder/structuredQuestionAnswer.ts:1-56`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:30-432`

No Driver/Service state-owner edits are allowed in Batch 6.

### Archived Expected Files Changed In Prompt/Audit Checkpoint

Docs:

- `docs/refactor/ai-builder-prompt-contract.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/retrospective-1.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-1.md`

If the loop requires a second implementation iteration, add the next numbered retrospective and Claude reconciliation. Do not pre-create them.

Bounded expected test changes:

- `backend/tests/integration/flows/test_ai_builder_edit_apply_regressions.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_router.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompts.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_repair.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py`

The integration and proposal-repair files are included because validation exposed stale test expectations in active AI Builder contract surfaces:

- `AddStepPayload`/`NewStepDraft` no longer accepts `output_mode` for new edit steps; the backend derives it.
- `retry_forced_tool_after_text` returns an event tuple for processed repair output.

Validation-only existing tests, not expected to change unless they reveal a real gap:

- `backend/tests/integration/flows/test_ai_builder_session_api_regressions.py`
- `backend/tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_knowledge_pack.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_repair_transport.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py`

Production source files expected to change in 6a:

- none

### Archived Validation Commands

Docker was blocked by host policy when running `docker ps --format '{{.Names}}'`, so this plan uses local fallback validation. If Docker becomes available, run the same commands inside `eneo-41ae93-eneo-1`.

Backend targeted tests:

```bash
cd backend && uv run pytest \
  tests/integration/flows/test_ai_builder_session_api_regressions.py \
  tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py \
  tests/integration/flows/test_ai_builder_edit_apply_regressions.py \
  -q
```

Backend prompt/repair/SSE unit pins:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompts.py \
  tests/unittests/flows/ai_builder/test_ai_builder_knowledge_pack.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair_transport.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py \
  -q
```

Type check targeted files:

```bash
cd backend && uv run pyright \
  tests/integration/flows/test_ai_builder_edit_apply_regressions.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompts.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py
```

Lint targeted files:

```bash
cd backend && uv run ruff check \
  tests/integration/flows/test_ai_builder_edit_apply_regressions.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompts.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py
```

Import boundaries:

```bash
cd backend && uv run lint-imports --no-cache
```

Docs/source drift checks:

```bash
git diff --check -- \
  docs/refactor/ai-builder-prompt-contract.md \
  docs/refactor/execution/batch-6-ai-builder-contract-split \
  backend/tests/integration/flows/test_ai_builder_session_api_regressions.py \
  backend/tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py \
  backend/tests/integration/flows/test_ai_builder_edit_apply_regressions.py \
  backend/tests/unittests/flows/ai_builder
```

Frontend AI Builder protocol/type checks only if frontend protocol files are touched, which is not expected in 6a:

```bash
cd frontend/apps/web && bun run check
```

### Archived Loop And Claude Review Plan

The prompt/audit checkpoint followed the standard loop protocol. See
`docs/refactor/execution/loop-protocol.md` for the live process; do not copy this
archived checklist forward as an active plan.

## Archive - Repair Contract Hardening Plan (Committed At fd5b725b)

Outcome: shipped in `fd5b725b flows: harden ai builder repair retry contract`.
The repair checkpoint added missing `recoverable_parse` behavior pins and
replaced a local primitive retry-state bundle with
`_ProposalRepairRetryState`. No repair modules were split and no retry budgets,
SSE events, audit behavior, planner behavior, or frontend behavior changed.

### Start Gate

| Check | Result |
|---|---|
| `git log --oneline --max-count=8` | latest commit is `4cd874c7 flows: pin ai builder prompt and audit contracts` |
| `git status --short --branch` | branch `feature/refactor-flows-flowai`; dirty files limited to `frontend/packages/ui/src/icons/types.d.ts`, `scripts/run_codex_review.sh`, `PRODUCT.md` |
| `git diff --cached --name-only` | no staged files |
| Docker check | `docker ps --format '{{.Names}}'` blocked by host execution policy; local fallback validation planned |

Known dirty files are unrelated and must remain untouched:

- `frontend/packages/ui/src/icons/types.d.ts`
- `scripts/run_codex_review.sh`
- `PRODUCT.md`

### Scope

This narrow slice covers AI Builder repair contract hardening only. It does not
restart the prompt/audit contract checkpoint and does not start the create/edit
proposal split.

The previous repair inventory found active repair behavior, not stale
compatibility to extract or delete. This slice therefore narrows the repair
work to one behavior pin plus one possible local consolidation. It is not a
module extraction slice, and it does not claim to finish the broader
create/edit/repair separation acceptance criterion.

PRD-005 constraints quoted for this slice:

- "No fake one-method interfaces are introduced."
- "no interface unless two real implementations exist."

Relevant PRD-005 acceptance criteria:

- "Proposal create/edit/repair responsibilities are separated."
  - This slice only tightens the repair responsibility boundary. The create/edit
    proposal split remains open after this slice.
- "Tests cover create/revise/approve/apply and repair failures."
  - This slice covers repair-failure tests and keeps existing
    create/revise/approve/apply integration tests in validation. It does not add
    new create/revise/approve/apply behavior.

### Current Repair Contract Inventory

| Repair surface | Current owner | Evidence | Contract state | Action |
|---|---|---|---|---|
| Semantic planner repair | `backend/src/intric/flows/ai_builder/ai_builder_repair.py` | retry constants and typed outcomes at lines 76-86 and 246-286; repair helper at lines 289-354 | Already has typed `RepairOutcome`, explicit retry constants, and behavior pins in `test_ai_builder_repair.py:93-307` | No production change planned |
| Parse repair | `backend/src/intric/flows/ai_builder/ai_builder_repair.py` | typed `ParseRepairOutcome` at lines 357-379; repair helper at lines 406-470; prompt anchors at lines 382-403 | Already separated from semantic repair and pinned by `test_ai_builder_parse_repair.py:207-391` plus prompt artifact test | No production change planned |
| Planner repair loop accounting | `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py` | loop accounting and parse-repair handling at lines 253-365 and 388-454 | Already owns planner-loop retry semantics and has behavior pins in `test_ai_builder_orchestration_pipeline.py:222-638` | Validation only |
| Proposal tool repair | `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` | retry availability/consume helpers at lines 127-148; loop primitives initialized at lines 219-221; consume/update at lines 329-342 | Has a duplicated primitive concept: `attempts_remaining`, `extra_retry_available`, and `retry_count` travel together but are not one value | Candidate for a small local frozen value object |
| Proposal JSON text fallback | `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` | direct JSON text handling at lines 391-430 and 505-581 | Active repair behavior, not compatibility. Pinned by `test_ai_builder_proposal_repair.py:107-159` | Preserve |
| Proposal forced-tool retry | `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` | forced call path at lines 432-500 | Active repair behavior. Pinned by `test_ai_builder_proposal_repair.py:55-105` | Preserve |

### Hardening Decision

There is one concrete repair contract weakness worth planning:

| Concept | Existing primitive locations | Problem | Canonical home | Planned fix |
|---|---|---|---|---|
| Proposal repair retry state | `_retry_budget_available` lines 127-135, `_consume_retry_budget` lines 138-148, loop state lines 219-221 and 329-342 | Three primitives represent one invariant: normal retry slots, one extra recoverable-parse slot, and human-facing retry ordinal. A future edit can update one without the others. | `ai_builder_proposal_repair.py`, local to proposal tool repair | Replace the primitive bundle with a small frozen `_ProposalRepairRetryState` value object that owns `can_retry`, `consume`, and next retry ordinal. Preserve numeric budgets and behavior exactly. |

Why this is not a fake interface:

- It is a value object, not a Protocol/ABC/adapter.
- It has no second implementation and does not pretend to be extensible.
- It removes duplicated primitive handling inside the current canonical owner.
- It stays local to `ai_builder_proposal_repair.py`; no module split, symbol move, package rename, or new subpackage.
- PRD-005 forbids fake one-method interfaces at
  `docs/refactor/prd/PRD-005-ai-builder-architecture.md:70-72`. The proposed
  object is a frozen local dataclass carrying state; it exposes no abstract
  method and owns no behavior dispatch.

If review identifies a smaller-cost, equal-benefit alternative, prefer it.
The minimum outcome is now the missing recoverable-parse behavior pin; a
no-production-change path still ships that test and the curated process
artifacts.

### Retry-State Transition Table

The value object must preserve the current `_consume_retry_budget` semantics:

| Current state | Failure kind | Expected transition |
|---|---|---|
| `attempts_remaining > 0`, extra retry available or unavailable | any failure kind, including `recoverable_parse` | decrement `attempts_remaining` by 1, preserve `extra_retry_available`, increment the human-facing retry ordinal |
| `attempts_remaining == 0`, `extra_retry_available is True` | `recoverable_parse` | keep `attempts_remaining` at 0, set `extra_retry_available` to false, increment the human-facing retry ordinal |
| `attempts_remaining == 0`, `extra_retry_available is False` | `recoverable_parse` | no retry is available; emit the existing typed self-correction error event |
| `attempts_remaining == 0` | `parse`, `validation`, `quality`, or any non-extra failure kind | no retry is available; emit the existing typed self-correction error event |

The retry ordinal must keep the current temperature and feedback behavior:

- retry ordinal 0 uses `self_correction_temperature`
- retry ordinal 1 and later use `self_correction_bumped_temperature`
- feedback for ordinal 1 starts with `CORRECTION STILL INVALID:`
- feedback for ordinal 2 and later starts with `FINAL CORRECTION ATTEMPT`

Diff budget: the production change must stay at or below 60 net LOC. If the
production diff exceeds that, stop and re-plan instead of widening the slice.

### Prompt Contract Anchors That Must Stay Protected

The existing artifact and test must not be weakened. These anchors must keep
passing through `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py`:

- `base_planning_state_version`
- `outline_flow`
- `edit_flow`
- exact `ref` values
- `architecture_commit: null`
- single raw JSON object
- no markdown/code-fence wrapping via `Do NOT wrap`

`docs/refactor/ai-builder-prompt-contract.md` may be edited only to add anchors.
No anchor removals, renames, or looser assertions are planned.

### Behavior Pins Before Or With Production Hardening

Existing behavior pins that must remain green:

- `test_ai_builder_repair.py:93-107` pins parse-repair budget and raw JSON prompt obligations.
- `test_ai_builder_repair.py:109-307` pins semantic repair eligibility, prompt detail/code behavior, drift blocking, preservation-by-absence, and retry count constants.
- `test_ai_builder_parse_repair.py:207-391` pins parse-repair outcomes, diagnostics, single retry, and truncation behavior.
- `test_ai_builder_orchestration_pipeline.py:222-638` pins planner repair-loop accounting, non-repairable short-circuit, drift handling, malformed semantic-repair parse repair, and budget exhaustion.
- `test_ai_builder_proposal_repair.py:162-195` pins proposal self-correction retry budget and first/final correction prompt wording.
- `test_ai_builder_proposal_repair.py:273-453` pins temperature bumping, conversational bail behavior, legitimate info-request text, and stronger prompt timing.

Additional behavior pins planned regardless of whether the value object proceeds:

- `test_recoverable_parse_grants_exactly_one_extra_retry_after_normal_budget_exhausted`
  should exercise `request_self_correction` through the public repair helper and
  prove the existing extra-retry path gets exactly one additional correction
  after normal retries are exhausted.
- Add the paired negative case: non-`recoverable_parse` failure kinds such as
  `parse` or `validation` must not trigger an extra retry after normal retries
  are exhausted.
- Preserve the existing test that on normal retry slots the repair loop performs
  exactly one initial correction plus three retries; if the value object
  proceeds, the recoverable-parse case must prove the extra slot does not
  consume or extend the normal `MAX_SELF_CORRECTION_RETRIES = 3` budget.
- Prove the final event payload shape is unchanged: after the extra retry is
  consumed, the next failed result emits the same typed self-correction error
  event instead of another retry.

No test will assert private helper calls merely to protect the refactor.

### Forbidden Files And Actions

Forbidden files for this slice:

- `backend/src/intric/flows/ai_builder/ai_builder_repair_transport.py`
- `backend/src/intric/flows/ai_builder/ai_builder_edit_repair.py`
- `backend/src/intric/flows/ai_builder/ai_builder_router.py` except pre-existing repair test import updates, which are not expected
- `backend/src/intric/flows/ai_builder/ai_builder_orchestration_pipeline.py`
- `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py`
- frontend files
- migrations

Forbidden actions:

- no `RepairPolicy` Protocol, ABC, one-method interface, or one-implementation adapter
- no new subpackages
- no module renames
- no symbol moves across files
- no SSE event name, payload, or ordering changes
- no audit behavior changes
- no logging behavior changes
- no numeric retry budget changes:
  - `MAX_ORCHESTRATOR_REPAIR_RETRIES = 3`
  - `MAX_PARSE_REPAIR_RETRIES = 1`
  - `MAX_SELF_CORRECTION_RETRIES = 3` in `backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py:172`
  - existing proposal self-correction retry semantics
- do not share a proposal retry-state value object with semantic or parse
  repair; the retry domains are different
- no create/edit proposal split
- no planner-turn extraction
- no router/presenter thinning
- no frontend protocol work
- no package rename
- no `intric.*` to `eneo.*` rename

### Expected Files To Change

Expected production file if the value-object hardening proceeds:

- `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py`

Expected tests:

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py` only as validation, not expected to change
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_repair.py` only as validation, not expected to change
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py` only as validation, not expected to change
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py` only as validation, not expected to change

`test_ai_builder_proposal_processor.py` is expected because validation exposed
stale retry-config expectations for the already-current nullable edit-context
keys.

Expected docs/process artifacts:

- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/retrospective-2.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-2.md`

If no production change proceeds, expected files narrow to:

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/plan.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/journal.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/retrospective-2.md`
- `docs/refactor/execution/batch-6-ai-builder-contract-split/claude-reconciliation-2.md`

### Validation Commands

Implementation-order row for Batch 6 gives validation labels:

- AI Builder integration tests
- SSE event tests
- frontend AI Builder tests

For this repair-only backend slice, exact validation commands are:

AI Builder integration tests:

```bash
cd backend && uv run pytest \
  tests/integration/flows/test_ai_builder_session_api_regressions.py \
  tests/integration/flows/ai_builder/test_ai_builder_apply_to_draft.py \
  tests/integration/flows/test_ai_builder_edit_apply_regressions.py \
  -q
```

Repair, prompt-contract, parser, pipeline, and SSE/error unit tests:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_router.py \
  tests/unittests/flows/ai_builder/test_ai_builder_failure_events.py \
  -q
```

Targeted pyright:

```bash
cd backend && uv run pyright \
  src/intric/flows/ai_builder/ai_builder_proposal_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py
```

Targeted ruff:

```bash
cd backend && uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_proposal_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py \
  tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py
```

Import boundaries:

```bash
cd backend && uv run lint-imports --no-cache
```

Diff hygiene:

```bash
git diff --check -- \
  backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_prompt_contract_artifact.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_repair.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_orchestration_pipeline.py \
  docs/refactor/execution/batch-6-ai-builder-contract-split
```

Committed-text hygiene:

```bash
rg -n "6b|6c|Batch 6|repair extraction" \
  backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py \
  backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  docs/refactor/ai-builder-prompt-contract.md
```

Expected: no matches outside process artifacts. If the production file or test
has an intentional ordinary word match, classify it before commit.

Frontend AI Builder tests are not run because this slice forbids frontend edits
and does not touch frontend protocol/event surfaces. If Claude identifies a
frontend-facing repair payload risk with file:line evidence, stop and ask for a
scope decision instead of expanding this slice.

### Claude Plan Review

Before implementation, run Claude peer-loop against this plan and ask whether
the value-object hardening genuinely improves reliability/maintainability or
whether this should be a no-production-change checkpoint. Resume the same
session for verification after revisions. Do not implement until the plan has
green light or a documented, evidence-backed disagreement.

## Active Carry-Forward (Post-Revert)

| Item | PRD-005 status | Evidence / next trigger |
|---|---|---|
| `_handle_edit_flow` remains in `AIBuilderProposalProcessor` | deferred within "Proposal create/edit/repair responsibilities are separated" | The edit proposal checkpoint moved edit-domain composition but left shared event streaming and self-correction retry orchestration in the processor spine. Reopen only with a measured boundary that moves real shared-spine responsibility without callback-heavy reach-back. |
| Planner turn lifecycle single owner | open / partially owned by `ai_builder_planner_turn.py`; send-lock lifecycle remains in `AIBuilderPlanner.send_message` | The send-lock-only extraction reduced `AIBuilderPlanner.send_message` by 27 LOC against the required 80 LOC and created a 163 LOC module against the 150 LOC cap. Reopen only under the no-go re-entry trigger above. |
| Chained-call lease-loss SSE mapping in `send_message` | open / behavior gap | `ai_builder_planner.py:1471-1485` chained `confirm_requirements` dispatch is not covered by the existing `session_send_lease_lost` handler. Add the lease-lost re-poll plus SSE mapping the next time `send_message` is touched, even if no extraction is performed. |
| Router SSE wrapper is thin | open | Router/presenter thinning is the next candidate slice, but it must begin with a measured `ai_builder_router.py` inventory and numeric success gate before source edits. |
| AI Builder generated/manual type drift | partially addressed | Frontend protocol aliasing now uses generated-backed aliases where schemas exist. Remaining gaps are backend-generated schema coverage for AI Builder SSE payloads, `SendMessageRequest.edit_context`, and structured edit-result metadata beyond generic `PlanResponse.edit_result_json`. |
| `ai_builder_models.py` star-barrel migration | deferred | Keep deferred until AI Builder owners are clearer; do not create compatibility re-exports. |
| `@intric/intric-js` package naming | deferred | Batch 5 decision keeps the package name for now; no package rename in Batch 6 slices. |
| Flow runtime UI-owned projections | out of scope | `FlowDocumentRenderLimits`, `FlowRunOutputPayload`, and related Flow runtime projections are not AI Builder protocol types. |

## Non-Goals

- Do not restart the rejected send-lock source extraction from this cleanup
  pass.
- Do not start router/presenter thinning from this cleanup pass.
- Do not start frontend protocol work from this cleanup pass.
- Do not modify PRD-005 in this cleanup pass.
- Do not split `AIBuilderService` or planner modules from this cleanup pass.
- Do not delete active repair behavior.
- Do not preserve or add compatibility for imaginary users.
- Do not touch frontend state ownership.
- Do not touch known unrelated dirty files.
