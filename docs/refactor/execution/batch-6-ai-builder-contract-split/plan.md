# Batch 6 - AI Builder Contract Split

## TL;DR

- This plan intentionally slices Batch 6 and implements only 6a in this session.
- 6a is behavior pins and prompt-contract audit only: tests, docs, and batch audit artifacts.
- No structural production refactor in `backend/src/intric/flows/ai_builder/*.py` is allowed in 6a.
- Docker validation is preferred, but `docker ps` was blocked by host execution policy in this session; local fallback validation is planned.
- Stop after 6a reaches the commit boundary. Do not continue to 6b without explicit user approval.

## Start Gate

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

## Scope Decision

Batch 6 is PRD-005 AI Builder contract split. This session implements only:

### 6a - Behavior Pins And Prompt-Contract Audit

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

## Source-Of-Truth Owners

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

## AI Builder File Inventory

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

## Sliced Batch Plan

| Slice | Goal | Production code edits? | Stop gate |
|---|---|---:|---|
| 6a | Behavior pins and prompt-contract audit | No | commit boundary after tests/docs only |
| 6b | Repair policy classification and extraction | Yes, only after repair inventory | user approval after 6a |
| 6c | Split create vs edit proposal processing | Yes, no fake one-method interfaces | after 6b |
| 6d | Planner turn use case | Yes, define lock, prompt, LLM, mutation, persistence, rollback, telemetry boundaries | after 6c |
| 6e | Thin router and presenter | Yes, move response shaping/use-case behavior only where owner is clear | after 6d |
| 6f | Frontend protocol aliases only | Type-only frontend changes; no Driver/Service state refactor | after backend contract is stable |

If 6a cannot stay test/docs-only, stop and ask to split the batch further.

## Behavior Pins Before Refactors

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

## Prompt Contract Artifact Plan

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

## Repair Policy Inventory For 6b

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

## Router Thinning Plan For Later

| Router helper/endpoint | 6a action | Later owner candidate | Reason |
|---|---|---|---|
| `_authorize_ai_builder_request` | read-only | router/auth adapter | HTTP/auth concern stays in router boundary |
| `_ai_builder_error_response` | read-only | presenter or API model helper | response example shaping can move only after OpenAPI pins |
| `_to_session_response`, `_to_plan_response` | read-only | presenter | response shaping candidate for 6e |
| `send_message` SSE wrapper | test only | router + presenter/use case split | HTTP stream and terminal event ordering must stay explicit |
| `create_session` audit | test only | possibly application use case later | 6a pins current audit metadata before any move |
| `approve_plan` and `apply_plan` audit | test only | possibly plan lifecycle/use case later | 6a pins current audit metadata before any move |
| `revise_plan` | test only | proposal/edit use case later | 6c/6e can split after behavior pins |

## Frontend Protocol Type Scope

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

## Expected Files To Change In 6a

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

## Validation Commands

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

## Loop And Claude Review Plan

1. Write this `/plan` and initial journal.
2. Run Claude peer loop iteration 1 against the 6a plan.
3. Verify Claude findings locally.
4. Revise the plan where findings are valid.
5. Run Claude peer loop iteration 2 with the same session and require green light, or document disagreement with evidence.
6. Implement 6a tests/docs only.
7. Run validation.
8. Run retrospective.
9. Run Claude implementation review and reconciliation.
10. Stop at commit boundary and report staging list, do-not-stage list, validation, risks, suggested commit, and whether 6b is blocked.

## Carry-Forward Risks From Batch 5

| Risk | Status in 6a | Reason |
|---|---|---|
| `FlowDocumentRenderLimits`, `FlowRunOutputPayload`, and related Flow runtime UI-owned projections | out of scope | These are Flow runtime UI projections, not AI Builder protocol types |
| Frontend baseline/typecheck drift | out of scope unless frontend protocol touched | 6a is backend test/docs only |
| `@intric/intric-js` package naming | deferred | Batch 5 decision keeps package name for now; no rename in Batch 6 |
| AI Builder manual protocol drift | inventory only | 6f owns generated alias mapping; 6a only records current generated/manual surfaces |
| Frontend SSE/open-flow protocol aliasing | deferred | Existing frontend tests pin driver behavior; generated alias mapping belongs to 6f and state ownership belongs to Batch 7 |

## Non-Goals

- Do not start 6b.
- Do not thin `ai_builder_router.py` in 6a.
- Do not split `AIBuilderService` or planner modules in 6a.
- Do not delete active repair behavior.
- Do not preserve or add compatibility for imaginary users.
- Do not touch frontend state ownership.
- Do not touch known unrelated dirty files.
