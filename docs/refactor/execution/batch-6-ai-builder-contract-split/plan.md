# Batch 6 - AI Builder Contract Split

## TL;DR

- Active plan: continue after `4cd874c7 flows: pin ai builder prompt and audit contracts` with repair contract hardening only.
- User approval to continue this next narrow repair slice is recorded in the 2026-04-30 prompt that starts from `4cd874c7`.
- The prompt/audit contract checkpoint is archived below; it was committed at `4cd874c7` and is no longer the active implementation scope.
- The active repair plan starts at `## Repair Contract Hardening Plan`.
- Docker validation is preferred, but `docker ps` remains blocked by host execution policy in this session; local fallback validation is planned.

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

## Repair Contract Hardening Plan

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

## Carry-Forward Risks From Batch 5

| Risk | Status in repair slice | Reason |
|---|---|---|
| `FlowDocumentRenderLimits`, `FlowRunOutputPayload`, and related Flow runtime UI-owned projections | out of scope | These are Flow runtime UI projections, not AI Builder protocol types |
| Frontend baseline/typecheck drift | out of scope unless frontend protocol touched | This repair slice is backend source/tests/docs only |
| `@intric/intric-js` package naming | deferred | Batch 5 decision keeps package name for now; no rename in this slice |
| AI Builder manual protocol drift | deferred | Frontend generated alias mapping remains a later AI Builder protocol-type slice |
| Frontend SSE/open-flow protocol aliasing | deferred | Existing frontend tests pin driver behavior; generated alias mapping belongs to 6f and state ownership belongs to Batch 7 |

## Non-Goals

- Do not start the create/edit proposal split.
- Do not thin `ai_builder_router.py`.
- Do not split `AIBuilderService` or planner modules.
- Do not delete active repair behavior.
- Do not preserve or add compatibility for imaginary users.
- Do not touch frontend state ownership.
- Do not touch known unrelated dirty files.
