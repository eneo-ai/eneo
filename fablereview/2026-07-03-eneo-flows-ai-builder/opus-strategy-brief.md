# Opus Strategy Brief: Fable Review Program For Flow AI Builder

## Goal

We need to use scarce Claude Fable budget for the highest-ROI pre-production review of Eneo Flow AI Builder and Flows. The user wants honest architecture, maintainability, robustness, data model, database schema, runtime/dataflow, token/RAG efficiency, API consumer DX, and future debt findings. The immediate focus is Flow AI Builder, especially:

- conversational discovery and whether it asks relevant questions before producing a plan;
- user uploaded files such as Word templates, legal knowledge, examples, and how those files influence questions and plan semantics;
- `underlag till text`, input fields, input/output JSON schemas, structured field extraction, and cross-step data transfer;
- repair/self-correction/fallback dependence and whether invalid plans should become harder to produce instead of repaired later;
- JSONB vs relational storage for long-term maintainability and 50k-user scale;
- what can be deleted, moved, merged, or simplified now because this is pre-production.

## Current Evidence Anchors

### Builder turn flow and early proposal jump

- `backend/src/eneo/flows/ai_builder/ai_builder_action_policy.py:25-29` defines only two core architectural slots: `primary_runtime_input` and `terminal_output`.
- `backend/src/eneo/flows/ai_builder/ai_builder_turn_controller.py:112-137` chooses one deterministic action in order: ask question, commit architecture, confirm requirements, propose plan.
- `backend/src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py:194-246` can commit architecture and then immediately dispatch requirements confirmation in the same turn.
- `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderQuestion.svelte:45-60` auto-submits a single-select option unless `requiresConfirm` is true.
- Screenshots show a simple Swedish prompt ("Jag vill bygga ett transkriberingsflöde") receiving one post-processing question, then jumping to a summary/plan after one selected option. The desired product behavior is more ChatGPT-like discovery for ambiguous work such as audio -> legal analysis -> fill a Word template -> output PDF/DOCX.

### Attachments and discovery

- `backend/src/eneo/flows/ai_builder/ai_builder_planner_request_preparation.py:152-208` returns `ServerOutputPrepared` for question/commit/confirm decisions before building attachment context.
- `backend/src/eneo/flows/ai_builder/ai_builder_planner_request_preparation.py:219-230` builds `attachment_context` only for proposal generation.
- `backend/src/eneo/flows/ai_builder/ai_builder_attachment_context.py:9-20` caps attachment context at 4k chars per file / 12k chars total.
- `backend/src/eneo/flows/ai_builder/ai_builder_attachment_context.py:73-78` treats uploaded files generically as "Reference material" for planning, without role semantics such as template, legal source, sample input, policy, schema, or desired output example.

Concern: uploaded DOCX templates/laws may not shape discovery questions or architecture commits, and may only arrive after the server already decided it has enough information.

### Repair, fallback, and post-hoc correction

- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:314-322` retries when the model returns text instead of the forced proposal tool.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:547-558` enters self-correction on tool argument parse failure.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:599-616` enters self-correction when proposal processing returns no events.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:61` allows up to 3 self-correction retries.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:368-402` builds retry prompts telling the model not to emit backend-owned mechanics.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:466-620` implements the core self-correction loop, repeated tool parsing, validation feedback, and retry state.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:689-781` tries to force a tool call after conversational text.
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:800-845` accepts JSON object text as a fallback tool argument payload.
- `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py:162-177` says backend normalizes low-level references because the model may describe semantic intent but cannot own exact mechanics.
- `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py:796-835` selects schema-aware underlag through broad/semantic/summary/floor/fallback heuristics.
- `backend/src/eneo/flows/ai_builder/ai_builder_plan_edit_context.py:260-274` deterministically patches some scoped edits because the LLM cannot reliably edit backend-inserted steps.

Question: which repair paths are valid model-boundary defenses, and which are symptoms of a brittle planner/proposal contract that should be redesigned now?

### JSONB and relational storage

- `backend/src/eneo/database/tables/flow_tables.py:2076-2080` stores `builder_sessions.conversation` as JSONB.
- `backend/src/eneo/database/tables/flow_tables.py:2092-2100` stores `builder_sessions.latest_plan_id`, `planning_state_jsonb`, and `planning_state_version`.
- `backend/src/eneo/database/tables/flow_tables.py:2150-2174` uses relational `builder_session_files` for session-file links.
- `backend/src/eneo/database/tables/flow_tables.py:2195-2199` stores `builder_plans.proposal_json` as JSONB plus `spec_hash`.
- `backend/src/eneo/flows/infrastructure/flow_jsonb_ownership.py:519-560` documents JSONB owners for conversation, planning state, and proposal snapshot.
- `backend/src/eneo/flows/ai_builder/planning_state.py:1-191` defines a typed, versioned `PlanningState` with strict Pydantic validation and embedded version fields.

Question: which JSONB fields are justified as immutable/session snapshots, and which would create long-term queryability, migration, audit, or scale problems if the product reaches 50k users?

### Prior verified Fable findings from 2026-07-02

- RAG retrieval uses full composed `prepared.step_input.text`.
- File/audio/document `flow_input` can compile `{{ step_input.text }}` while a run/rerun reaches runtime without files.
- Manual/UI binding validation is weaker than Builder validation.
- Builder accepts array item paths that runtime rejects.
- `INTENTIONAL_PARTIAL` underlag can silently preserve too-narrow source.
- Whole-plan edits can leave stale literal `step_N` aliases.
- `STEP_INPUT_KEY_SHAPES` drifted from runtime metadata.
- Structured refs into contract-less JSON steps are not strongly fenced.

## Question For Opus

Please act as a skeptical strategy partner before we spend Fable budget.

1. Should we use one broad Fable session or multiple narrower Fable sessions? Recommend the optimal number and exact scope boundaries. The goal is maximum true issue discovery and long-term architecture value, not minimizing model calls.
2. If multiple sessions, should they run in parallel or sequentially? What dependencies should flow from one prompt to another?
3. Which scope deserves the first Fable call if budget unexpectedly runs out?
4. How should we frame repair/fallback/self-correction so Fable separates valid model-boundary resilience from avoidable architecture brittleness?
5. How should we frame JSONB vs relational storage so Fable gives actionable long-term guidance for 50k-user scale instead of generic "JSONB bad" advice?
6. What should we explicitly exclude from Fable to avoid wasting scarce review quality?
7. Apply the Ponytail lens: what can likely be deleted, merged, moved, or simplified instead of polished?

Return:

- `Summary`
- `Recommended Fable Split`
- `Prompt Requirements`
- `What To Exclude`
- `Risks Or Blind Spots`
- `Recommended Next Step`
- `Confidence`
