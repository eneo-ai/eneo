# Fable Session Plan For Flow AI Builder Review

## TL;DR

Use multiple focused Fable sessions, not one broad architecture essay.
Run the proposal repair boundary session first because it is the clearest delete/merge opportunity and directly addresses the user's concern that we should make invalid states harder to produce instead of relying on repair.
Run the compiler/topology/runtime-contract session second because it decides where underlag, JSON paths, RAG query intent, and publish/runtime validation should be owned after repair is narrowed.
Run the planning-state/JSONB/data-model session third only if budget allows now; otherwise keep the agent/Codex findings and run Fable later.
Every session must produce findings, deletions, "not worth fixing", acceptance criteria, tests, and Codex verification questions.

## Proposed Split

| Session | Priority | Output file | Scope | Why this needs Fable |
|---|---:|---|---|---|
| 01 | Highest | `fable-01-proposal-repair-boundary-review.md` | Proposal submission, self-correction, forced tool retry, JSON-text fallback, create/edit proposal processors, create intent normalization, create feedback, proposal finalization, fake seams. | This directly answers whether repair is a valid model-boundary defense or compensating for brittle internal contracts. It is also the clearest tomorrow-sized delete/merge path. |
| 02 | High | `fable-02-compiler-topology-runtime-contracts-review.md` | Create/edit compilers, step topology, underlag/source material, `input_bindings.question`, JSON paths, RAG query derivation, output contracts, shared publish/runtime validation. | This is the core correctness path after repair is narrowed: Builder must compile valid specs without broad post-hoc normalization, and runtime must preserve source details/knowledge intent. |
| 03 | Medium-high | `fable-03-planning-state-jsonb-scale-review.md` | PlanningState vs discovery/profile truth, Builder conversation/proposal JSONB, commit spine, JSONB-vs-relational trade-offs, 50k-user scale, API/data-schema debt. | This is important, but current agent/Codex evidence is already strong. Run after sessions 01-02 unless Fable budget is explicitly plentiful. |

## Why Not One Huge Fable Session

- One broad prompt would mix product semantics, runtime contracts, persistence, API DX, and deletion strategy.
- The highest-risk questions require different evidence: proposal repair/contract code for session 01, compiler/runtime validator/resolver code for session 02, and schema/repo/JSONB code for session 03.
- Smaller sessions force Fable to make concrete trade-offs instead of returning generic "improve architecture" advice.
- Each session can produce implementation-ready work items for tomorrow.

## Sequential Or Parallel

Default recommendation: run sessions sequentially if Fable budget is tight.

- Run session 01 first. It may change what session 02 should inspect because a narrowed proposal contract changes what the compiler must own.
- Run session 02 second. It should read session 01 findings and decide which Builder outputs must become runtime contracts and which normalizers can be deleted.
- Run session 03 third or defer. It should read sessions 01-02 only if they propose moving persistent facts.

Parallel option: avoid it by default. Sessions 01 and 02 overlap enough that session 01's answer should sharpen session 02. Do not run session 03 in parallel unless the user explicitly chooses to spend the quota; it is less dependent on Fable's semantic strengths and already has strong subagent findings.

## Session 01 Prompt Requirements

Must ask Fable to inspect:

- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_tool_contracts.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_tool_parsing.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_proposal.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_edit_proposal.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_feedback.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_proposal_finalization.py`
- `backend/src/eneo/flows/ai_builder/planning_state.py`
- `backend/src/eneo/flows/ai_builder/pattern_registry.py`
- relevant proposal tests under `backend/tests/unittests/flows/ai_builder`

Key questions:

- Classify every repair/fallback/self-correction/normalization branch as `MODEL_BOUNDARY`, `CONTRACT_BRITTLENESS`, or `UPSTREAM_VALIDATION`.
- Which raw LLM/tool-call volatility repair should remain?
- Which broad catches, JSON-text fallbacks, schema patches, and quality-feedback string heuristics should be deleted or moved?
- What smaller semantic proposal contract would make invalid mechanics harder to produce?
- Which first implementation slice should be done tomorrow?
- What is not worth fixing now?

## Session 02 Prompt Requirements

Must ask Fable to inspect:

- `backend/src/eneo/flows/ai_builder/ai_builder_create_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_edit_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_underlag_policy.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_source_material.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_compiled_spec_preparation.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_validator.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_validation_references.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_json_schema_paths.py`
- `backend/src/eneo/flows/flow_authoring_spec.py`
- `backend/src/eneo/flows/flow_validators.py`
- `backend/src/eneo/flows/variable_resolver.py`
- `backend/src/eneo/flows/template_reference_analyzer.py`
- `backend/src/eneo/flows/runtime/step_definition_parser.py`
- `backend/src/eneo/flows/runtime/step_input_resolution.py`
- `backend/src/eneo/flows/runtime/step_execution_runtime.py`
- `backend/src/eneo/flows/runtime/rag_retrieval.py`
- `backend/src/eneo/assistants/references.py`

Key questions:

- Does Builder compile valid create/edit specs directly, or does it rely on broad post-compile normalizers?
- Which topology/dataflow/terminal-artifact transformations belong in create compiler, edit compiler, runtime validation, or migration compatibility?
- Is `input_bindings.question` the right pivot contract, and is it enforced everywhere that can create/publish flows?
- Should RAG have an explicit retrieval-query contract separate from full underlag?
- Does underlag/source-material policy preserve enough source details through transcription, JSON extraction, field selection, final PDF/DOCX rendering, and knowledge retrieval?
- Are JSON field paths, array paths, contractless JSON refs, and `step_input` keys runtime-equivalent across Builder, manual authoring, publish, and execution?

## Session 03 Prompt Requirements

Must ask Fable to inspect:

- `backend/src/eneo/database/tables/flow_tables.py`
- `backend/src/eneo/flows/infrastructure/flow_jsonb_ownership.py`
- `backend/src/eneo/flows/flow_capability_manifest.py`
- `backend/src/eneo/flows/ai_builder/planning_state.py`
- `backend/src/eneo/flows/ai_builder/planning_state_builder.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_discovery_profile_builder.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_user_question_metadata.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_conversation_metadata.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_repo.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_plan_store.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_domain_models.py`
- `backend/src/eneo/flows/flow_metadata.py`
- `backend/src/eneo/flows/flow_authoring_spec.py`
- `backend/src/eneo/flows/application/flow_authoring_command_service.py`
- `backend/src/eneo/flows/api/flow_models.py`

Key questions:

- Which JSONB fields should remain JSONB at 50k users because they are bounded snapshots?
- Which facts should become relational because they are queried, indexed, joined, retained, audited, migrated, or used for product analytics?
- Should `builder_sessions.conversation` stay JSONB, become `builder_session_messages`, or stay JSONB until search/audit/pagination appears?
- Is `PlanningState` version/cap governance real or dead speculative machinery?
- Should `BuilderSessionFiles` carry role metadata relationally, or should file roles live in typed planning state?
- Should the plan-store duplicate commit spine merge into `AIBuilderRepository` before bigger Builder work?
- Does discovery/profile re-derive legacy answers that should be a planning-state read model instead?

## Deferred Session: Discovery, Attachments, And Dialog Cadence

If sessions 01-02 leave Fable budget and the repair/compiler recommendations do not already settle the dialog contract, run a fourth or replacement session focused on:

- `ai_builder_planner_request_preparation.py`
- `ai_builder_attachment_context.py`
- `ai_builder_discovery_runtime.py`
- `ai_builder_discovery_decision_engine.py`
- `ai_builder_action_policy.py`
- `ai_builder_turn_controller.py`
- `ai_builder_server_decision_dispatch.py`
- `question_catalog.py`
- frontend question/chat/driver components.

Questions:

- What minimum signal from uploaded templates/laws/examples should reach discovery before proposal generation?
- When is single-select auto-submit plus one-turn commit cascade correct, and when is it a UX bug?
- Which deterministic discovery heuristics are load-bearing for reproducibility/audit, and which can be replaced by a bounded model critic?

## Required Fable Output Contract

Every session must include:

- five-line TL;DR;
- ratings 1-10 for architecture cleanliness, maintainability, runtime robustness, testability, production readiness, and API/data-model fitness where relevant;
- findings table with severity, problem, why it matters, file:line evidence, owner/fix, acceptance criteria, tests, risk/trade-off, confidence;
- "what is not worth fixing now";
- "what can be deleted, merged, moved, or simplified";
- "from-scratch clean architecture based on current learnings";
- "small implementation slices for tomorrow";
- "claims Codex must verify before implementation";
- explicit JSONB guidance in session 03;
- explicit repair/fallback guidance in session 01.

## Defer / Exclude

- Do not ask Fable to implement code.
- Do not ask Fable for broad repo documentation.
- Do not spend Fable on generic API DX until sessions 01-02 identify the actual contracts external consumers need.
- Do not let Fable invent plugin systems, generic orchestration frameworks, one-method interfaces, or compatibility layers.
- Do not ask Fable to preserve pre-production compatibility without persisted-data evidence.

## Current Recommendation Before Peer Review

Prepare all three prompts now.
Run session 01 first.
Run session 02 next only after session 01 returns and sharpens the contract.
Run session 03 if budget remains or if sessions 01-02 propose persistent state changes.
Run the discovery/attachments/dialog cadence session as a follow-up if session 01 does not already settle the conversation-contract question.
