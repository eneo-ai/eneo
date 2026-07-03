# Fable 04 Prompt: Discovery, Attachments, Dialog Cadence, And User Questions

You are Claude Fable running a max-effort, source-backed product-architecture and maintainability review for Flow AI Builder.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review the Flow AI Builder discovery/dialog architecture:

- whether it asks the right questions before producing a plan;
- why the user can click one option and immediately get a summary/plan-like conclusion;
- how uploaded files such as Word templates, legal references, schemas, examples, or desired outputs should influence discovery;
- whether deterministic discovery heuristics are load-bearing or overcomplicated;
- how to make the system more ChatGPT-like where that improves correctness without creating brittle AI slop.

This session is running in parallel with repair/compiler/data-model Fable sessions. Focus on discovery and user intent, not proposal compiler details unless necessary.

## Product Scenario

Observed screenshots:

- User says: `Jag vill bygga ett transkriberingsflöde`.
- Builder asks: `Vad ska flödet hjälpa dig göra med materialet?`
- User clicks an option such as `Beslut, nästa steg och uppföljning`.
- Builder jumps directly to a requirements summary and plan path.
- User expects a more conversational process for a workflow such as:
  - runtime audio upload;
  - transcribe speech;
  - use law/reference knowledge;
  - fill a Word template or create PDF/DOCX;
  - ask relevant follow-up questions until the Builder truly understands source material, target output, rules, template fields, and missing details.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-04-discovery-attachments-dialog-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `.codex/artifacts/fable-review-program-20260703/fable-source-evidence-packet.md`
- `.codex/artifacts/fable-review-program-20260703/agent-frontend-dialog-state-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-runtime-dataflow-review.md`
- `.codex/artifacts/ask-claude-fable-ai-builder-review-split-long-20260702T223104Z.md`

Then verify source yourself.

## Primary Source Scope

Inspect at least:

- `backend/src/eneo/flows/ai_builder/ai_builder_planner.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_planner_request_preparation.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_attachment_context.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_discovery_runtime.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_discovery_decision_engine.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_discovery_issue_rules.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_discovery_profile_builder.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_slot_classifier.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_semantic_adjudication.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_action_policy.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_turn_controller.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py`
- `backend/src/eneo/flows/ai_builder/question_catalog.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_question_state.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_user_question_metadata.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_requirements_state.py`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderQuestion.svelte`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderDriver.ts`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderChat.svelte`
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderInput.svelte`
- `frontend/apps/web/src/lib/features/flows/ai-builder/builderAttachmentRules.ts`
- relevant discovery/frontend tests.

## Important Known Evidence To Verify

- Attachment context appears to be built only in proposal generation, after early ask/commit/confirm decisions.
- `StructuredQuestionPayload.requires_confirm` affects option submit behavior, not backend turn cadence.
- Backend can chain architecture commit into requirements confirmation in one turn.
- Core architectural slots may only include `primary_runtime_input` and `terminal_output`.
- Single-select frontend questions auto-submit unless `requiresConfirm` is true.
- The current deterministic discovery stack contains many heuristic/vagueness rules.

## Questions To Answer

1. Is the one-question-then-summary behavior a reasonable product policy, or an over-eager state machine?

2. Which layer should own dialog cadence:
   - frontend submit policy;
   - backend turn controller;
   - action policy;
   - server decision dispatch;
   - question catalog;
   - planning state?

3. Which facts should make Builder ask another question before committing architecture?
   - output artifact type;
   - template role;
   - legal/reference role;
   - source-of-truth material;
   - runtime metadata/form fields;
   - target audience/style;
   - review/approval mode;
   - JSON schema requirements;
   - knowledge/RAG use;
   - final evidence/citations.

4. What minimum signal from uploaded files must reach discovery?
   - Do not assume full text should enter discovery.
   - Consider lightweight file roles/summaries: template, law/reference, sample input, desired output example, schema.

5. Should Builder attachments be role-tagged planning artifacts?
   - Where should roles live: relational `builder_session_files`, `PlanningState`, conversation metadata, proposal JSON, or transient prompt context?

6. Which deterministic discovery heuristics are load-bearing for reproducibility/audit, and which are overcomplicated AI-slop scaffolding?
   - Give two recommendations if audit reproducibility is legally required vs not required.

7. Should `post_processing_goal` question taxonomy/copy be changed for transcription flows?

8. Are frontend generated-type/metadata and option-key issues material to the product problem, or lower-priority cleanup?

9. What is the clean from-scratch discovery architecture based on current learnings?

10. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - conversation quality;
   - architecture cleanliness;
   - maintainability;
   - user intent robustness;
   - attachment/file semantics;
   - frontend/backend contract clarity;
   - testability;
   - production readiness.
3. `Conversation State Machine Map`
4. `Attachment Signal Flow Map`
5. `Question Ownership Map`
6. `Ranked Findings`
   - severity, problem, why it matters, evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence.
7. `Deterministic Discovery: Keep / Delete / Replace`
8. `Frontend Contract Cleanup`
9. `What Current Tests Already Cover`
10. `Missing Red Tests`
11. `What Is Not Worth Fixing`
12. `From-Scratch Cleaner Discovery Design`
13. `Tomorrow Implementation Slices`
14. `Claims Codex Must Verify`
15. `Challenge This Brief`
16. `Confidence`

## Guardrails

- Do not propose frontend-only fixes for backend turn-cadence behavior.
- Do not propose sending full uploaded files into discovery without token/security reasoning.
- Do not delete deterministic discovery heuristics without considering audit/reproducibility.
- Prefer role-based file semantics and explicit dialog contracts over prompt magic.
