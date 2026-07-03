# Agent Review: Frontend Dialog State, Question UX, And Generated Contracts

## TL;DR

The abrupt "one option -> summary/conclusion" behavior is backend-owned turn policy, not a frontend rendering bug.
`requires_confirm` only changes whether a selected option submits immediately; it does not prevent backend `architecture_committed` -> `requirements_summary` chaining after submission.
The highest-ROI frontend work is generated-contract cleanup and centralizing message metadata projections in the Driver.
The visible duplicate/overlap risk in question options should be handled at the Driver parser/catalog boundary, not with CSS or component heuristics.
Attachments have two legitimate frontend lifecycles: pending upload UI and persisted session attachments. Do not merge them.

## Ranked Findings

| Rank | Finding | Evidence | Proposed owner / fix |
|---:|---|---|---|
| 1 | "One answer -> summary" UX is intentional backend turn policy. Frontend changes alone will not make the conversation ChatGPT-like. | `backend/src/eneo/flows/ai_builder/ai_builder_action_policy.py:144`, `backend/src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py:204`, `backend/src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py:222`, `backend/src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py:249`, `backend/tests/unittests/flows/ai_builder/test_discovery_flow.py:1248`, `backend/tests/unittests/flows/ai_builder/test_discovery_flow.py:1264` | Keep dialog cadence owned by backend action policy / turn controller / dispatch. Characterize current same-turn behavior, then product-gate any unchaining. |
| 2 | Frontend duplicates generated/backend contract owners with handwritten metadata/edit-context types. | `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:40`, `frontend/apps/web/src/lib/features/flows/ai-builder/protocol.ts:168`, `frontend/apps/web/src/lib/features/flows/ai-builder/structuredQuestionAnswer.ts:9`, `frontend/packages/eneo-js/src/types/schema.d.ts:8703`, `frontend/packages/eneo-js/src/types/schema.d.ts:22451`, `frontend/packages/eneo-js/src/types/schema.d.ts:22945`, `frontend/packages/eneo-js/src/types/schema.d.ts:24090` | Use generated `@eneo/eneo-js` types for wire contracts. Keep only thin typed adapters where persisted metadata is intentionally narrower. |
| 3 | `FlowAIBuilderChat.svelte` re-derives conversation facts that should belong to `FlowAIBuilderDriver`. | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:56`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:716`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:770`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte:66`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte:136` | Driver should own projections like answered-question count and originating user request for a requirements summary. Chat should render. |
| 4 | Structured-question rendering has a duplicate-key risk and the `post_processing_goal` catalog options may feel semantically overlapping. | `backend/src/eneo/flows/ai_builder/ai_builder_event_models.py:17`, `frontend/apps/web/src/lib/features/flows/ai-builder/structuredQuestionAnswer.ts:31`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderQuestion.svelte:126`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:947`, `backend/src/eneo/flows/ai_builder/question_catalog.py:477` | Catalog owns domain choices; Driver parser should guarantee UI-safe uniqueness before rendering. |
| 5 | Attachment/file state split is mostly correct. | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte:28`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte:95`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:492`, `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts:629`, `backend/src/eneo/flows/ai_builder/ai_builder_service.py:360` | Keep pending uploads in input/upload manager and persisted attachments in Driver/session/backend. Do not merge lifecycles. |

## Ownership Map

| Concept | Proposed canonical owner |
|---|---|
| Dialog cadence | Backend `ai_builder_action_policy.py`, `ai_builder_turn_controller.py`, `ai_builder_server_decision_dispatch.py` |
| Submit policy for option click | Backend `StructuredQuestionPayload.requires_confirm` and catalog/question payload |
| Frontend session/messages/current plan | `FlowAIBuilderDriver` |
| Svelte reactivity/context facade | `FlowAIBuilderService` |
| API wire types | Generated `@eneo/eneo-js` |
| Pending uploads | `FlowAIBuilderInput` / attachment upload manager |
| Persisted attachments | Driver/session/backend |

## Delete / Merge Candidates

| Candidate | Reason |
|---|---|
| Local `AIBuilderPlanEditContext` type in `protocol.ts` | Generated type exists. |
| Broad `ChatMessage.metadata?: Record<string, unknown>` | Causes repeated unsafe metadata probes. |
| Chat's `answeredQuestionCount` scan | Duplicate derived state. |
| Chat's `latestUserRequestBefore` positional scan | Component owns conversation semantics. |
| Any Driver/Service merge | The boundary is useful: testable Driver and Svelte facade. |
| Any pending/persisted attachment lifecycle merge | They are different states. |

## Fable Follow-Up Questions

- Is the same-turn architecture-commit -> requirements-summary chain the right product architecture, or should it become a two-turn conversational policy?
- Which facts should make Builder keep asking versus commit architecture: output artifact type, source material role, template role, knowledge/rule source, structured fields, audience, review mode?
- Should `requires_confirm` be used more often for high-impact questions, or is that separate from the real backend turn-cadence issue?
- Should frontend contract cleanup happen before dialog UX changes so future SSE/message behavior is easier to review?
- Is the option overlap in `post_processing_goal` a catalog taxonomy problem, a visual parser problem, or both?
