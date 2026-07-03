# Fable Source Evidence Packet: Flow AI Builder

## TL;DR

Flow AI Builder should be reviewed as a pre-production architecture, not a legacy surface.
The highest-risk current shape is not one isolated bug; it is the interaction between conversation gating, attachments, proposal repair, dataflow compilation, runtime contracts, and JSONB session state.
Fable should separate valid model-boundary resilience from repair logic that compensates for unclear internal contracts.
Fable should also judge which JSONB fields are justified snapshots and which should become relational or indexed before scale.
Every recommendation should say what to delete, merge, move, or make canonical.

## Review Ground Rules

- Use file:line evidence for concrete claims.
- Apply the Ponytail lens: delete, reuse, merge, move, or simplify before adding.
- This code is pre-production for Flow / Flow AI Builder; do not preserve compatibility for imaginary users.
- Prefer one canonical owner for each concept.
- Separate valid boundary defenses from architecture that relies on repair because invalid states are easy to produce.
- For JSONB, do not say "JSONB bad" generically. Judge owner, version, validation, query pattern, indexability, migration path, and 50k-user scale.

## Key Product Scenario

The user asks in Swedish: "Jag vill bygga ett transkriberingsflöde."

Observed UI behavior from screenshots:

1. AI Builder asks one structured question: "Vad ska flödet hjälpa dig göra med materialet?"
2. The options list visually shows duplicated/overlapping "Beslut, nästa steg och uppföljning" rows.
3. After one option click, Builder jumps to a requirements summary and plan path.
4. The user expects a more ChatGPT-like dialog when the request is underspecified, especially for workflows like:
   - upload audio at runtime;
   - transcribe;
   - use law/reference knowledge;
   - fill a Word template or generate a PDF/DOCX;
   - preserve important details across steps.

## Evidence: Conversation Loop And Early Summary

| Concern | Evidence |
|---|---|
| The core architecture gate may be too narrow for real user workflows. | `backend/src/eneo/flows/ai_builder/ai_builder_action_policy.py:25-29` defines only `primary_runtime_input` and `terminal_output` as core architectural slots. |
| Turn control is deterministic and advances one phase in fixed priority. | `backend/src/eneo/flows/ai_builder/ai_builder_turn_controller.py:112-137` chooses ask question, then commit architecture, then confirm requirements, then propose plan. |
| Architecture commit can immediately dispatch requirements confirmation in the same server turn. | `backend/src/eneo/flows/ai_builder/ai_builder_server_decision_dispatch.py:194-246` commits architecture and can recursively dispatch the next requirements confirmation decision. |
| Single-select questions auto-submit on click unless the payload requires confirmation. | `frontend/apps/web/src/lib/features/flows/ai-builder/FlowAIBuilderQuestion.svelte:45-60` returns immediately after `onanswer(...)` for single-select questions without `requiresConfirm`. |
| Question policy suppresses many non-user-requirement questions and limits repeated asking. | `backend/src/eneo/flows/ai_builder/ai_builder_discovery_decision_engine.py:83-193` scores issues, suppresses questions by family/budget/confidence, and returns selected questions/assumptions. |
| Forced follow-up only happens after enough free discovery turns. | `backend/src/eneo/flows/ai_builder/ai_builder_discovery_runtime.py:334-354` requires free discovery and `_count_free_discovery_turns(conversation) >= 2`. |

Question for Fable: is the turn model intentionally simple, or is it prematurely collapsing discovery into summary/plan? Should "post-processing goal", template/document role, source of legal rules, output artifact mode, and runtime metadata sometimes be blocking architectural facts?

## Evidence: Attachments And Discovery

| Concern | Evidence |
|---|---|
| Attachment text is not built before ask/commit/confirm decisions. | `backend/src/eneo/flows/ai_builder/ai_builder_planner_request_preparation.py:152-208` returns `ServerOutputPrepared` for non-proposal turns before attachment context is built. |
| Attachment text only enters proposal prompt generation. | `backend/src/eneo/flows/ai_builder/ai_builder_planner_request_preparation.py:219-230` builds `attachment_context` inside the `GenerateProposal` path. |
| Attachment context is generic and role-less. | `backend/src/eneo/flows/ai_builder/ai_builder_attachment_context.py:73-78` labels uploaded content as generic "Reference material" for planning. |
| Attachment context has tight truncation caps. | `backend/src/eneo/flows/ai_builder/ai_builder_attachment_context.py:9-20` sets 4k chars per file and 12k total. |
| AI Builder upload accepts document/reference file types but not audio. | `frontend/apps/web/src/lib/features/flows/ai-builder/builderAttachmentRules.ts` should be inspected for allowed types and whether the UI communicates builder-context versus runtime-input semantics. |

Question for Fable: should Builder attachments be modeled as typed planning artifacts such as `template`, `reference_law`, `schema`, `sample_input`, `desired_output_example`, or `runtime_input_example`, and should those roles influence discovery before proposal generation?

## Evidence: Repair, Fallback, And Self-Correction

| Concern | Evidence |
|---|---|
| The first proposal call is forced to use the proposal tool, but missing tool calls still trigger a repair path. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:231-239` calls completion with `forced_tool_choice`; `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:314-322` retries after text. |
| Parse failures are repaired by another model call. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:547-558` enters self-correction when tool arguments cannot be parsed. |
| Validation/quality failures are repaired by another model call. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:599-616` enters self-correction when processing yields no events. |
| Self-correction can retry up to three times. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:61` defines `MAX_SELF_CORRECTION_RETRIES = 3`. |
| Retry prompt tells the model not to emit backend-owned mechanics. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:368-402` adds rules such as not emitting `input_source`, `input_type`, `input_bindings`, `output_mode`, refs, IDs, hashes, or timestamps. |
| The repair loop is substantial. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:466-620` performs repeated repair completion, tool parsing, validation classification, retry feedback, and terminal error handling. |
| The system tries forced tool retry after conversational text. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:689-781` builds a forced-tool prompt after text and processes the tool call if returned. |
| The system accepts JSON object text as fallback tool arguments. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:800-845` parses JSON object text and treats it as tool arguments. |
| Backend mechanically normalizes model-generated step mechanics. | `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py:162-177` states exact structured field paths, form joins, runtime-upload flags, and source invariants are backend-owned and normalized. |
| Some scoped edits are deterministic patches because the LLM cannot reliably edit backend-inserted steps. | `backend/src/eneo/flows/ai_builder/ai_builder_plan_edit_context.py:260-274` handles unambiguous step edits directly. |

Question for Fable: which repair mechanisms are legitimate model-boundary resilience, and which should be replaced by a smaller semantic proposal contract, deterministic plan construction, or typed intermediate state that makes invalid mechanics impossible?

## Evidence: Underlag, JSON Fields, And Runtime Contracts

| Concern | Evidence |
|---|---|
| `input_bindings.question` is intended as the pivot contract replacing implicit input. | `backend/src/eneo/flows/ai_builder/ai_builder_new_step_compiler.py` should be inspected around `compile_step_input_bindings`, source refs, and `derive_input_contract`. |
| Underlag policy rewrites certain text-composer steps using JSON prior fields. | `backend/src/eneo/flows/ai_builder/ai_builder_underlag_policy.py` should be inspected for `targeted_underlag_rewrite_indexes`, `final_assembler_rewrite_indexes`, and terminal renderer rewrites. |
| Targeted underlag chooses fields through semantic markers and fallback caps. | `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py:796-835` selects broad/semantic/summary/floor/fallback references. |
| Previous Fable finding: `INTENTIONAL_PARTIAL` underlag can preserve too-narrow source material. | Carry forward from `.codex/artifacts/fable-max-review-20260702/summary.md`. |
| Previous Fable finding: Builder accepts array item field paths runtime rejects. | Carry forward from `.codex/artifacts/fable-max-review-20260702/summary.md`. |
| Previous Fable finding: RAG retrieval uses full composed `prepared.step_input.text`. | Carry forward from `.codex/artifacts/fable-max-review-20260702/summary.md`. |

Question for Fable: should Builder compile a smaller typed semantic graph and let one compiler own underlag, JSON field paths, runtime input contracts, and RAG query intent?

## Evidence: JSONB, Relational Model, And Scale

| Field/Table | Evidence | Review question |
|---|---|---|
| `builder_sessions.conversation` JSONB | `backend/src/eneo/database/tables/flow_tables.py:2076-2080` | Keep JSONB append-only history, or split messages into relational rows for queryability, retention, partial loading, and 50k-user scale? |
| `builder_sessions.planning_state_jsonb` JSONB | `backend/src/eneo/database/tables/flow_tables.py:2092-2100` | Keep as versioned working snapshot, or move stable resolved slots/commit facts to relational columns/rows? |
| `builder_plans.proposal_json` JSONB | `backend/src/eneo/database/tables/flow_tables.py:2195-2199` | Keep as immutable proposal snapshot, or normalize plan steps if search/reporting/diff/audit matter? |
| `builder_session_files` relational | `backend/src/eneo/database/tables/flow_tables.py:2150-2174` | Is this sufficient without file role/type metadata for template/reference/sample semantics? |
| JSONB ownership ledger | `backend/src/eneo/flows/infrastructure/flow_jsonb_ownership.py:519-560` | Are owners, schema versions, and corruption behaviors enough for each JSONB field? |
| Typed planning state | `backend/src/eneo/flows/ai_builder/planning_state.py:1-191` | Is this a justified JSONB document, and does it capture the right facts? |

Question for Fable: which data should become first-class relational state before production because it will be queried, indexed, joined, retained, migrated, or audited? Which should remain JSONB because it is an immutable snapshot or bounded session document?

## Suggested Output Contract For Every Fable Session

Start with a five-line TL;DR, then include:

1. Honest ratings, 1-10:
   - architecture cleanliness;
   - maintainability;
   - runtime robustness;
   - API consumer DX where relevant;
   - data model/schema fitness;
   - testability;
   - production readiness.
2. Findings table with:
   - severity;
   - problem;
   - why it matters;
   - evidence;
   - proposed canonical owner/fix;
   - acceptance criteria;
   - tests required;
   - risk/trade-off;
   - confidence.
3. "What is not worth fixing now."
4. "What can be deleted, merged, moved, or simplified."
5. "If designing from scratch from today's learnings, what would be the clean architecture?"
6. "Small implementation slices for tomorrow."
7. "Claims Codex must verify before implementation."
