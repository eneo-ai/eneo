# Agent Review: Repair/Fallback Dependence And Fable Split

## TL;DR

Keep a small repair loop at the raw LLM/tool-call boundary.
Delete or move repair paths that catch compiler bugs, mutate strict payloads, or silently rewrite compiled specs.
The biggest owner drift is that proposal submission, create/edit proposal processors, create intent parsing, create dataflow, and step transition policy all repair different slices of "valid proposal."
Run three narrow Fable sessions: proposal repair boundary first, compiler/topology ownership second, planning-state plus JSONB/data-model third.
JSONB discipline is better than expected, but `builder_sessions.conversation`, queried `proposal_json` fields, and `metadata_json.form_schema` are the main 50k-user pressure points.

## Repair/Fallback Findings

| Finding | Evidence | Current owner | Proposed canonical home | Delete / merge | Acceptance / tests |
|---|---|---|---|---|---|
| Compiler and architecture failures can be routed into model self-correction, making product bugs look like bad model payloads. | `backend/src/eneo/flows/ai_builder/ai_builder_create_proposal.py:120`, `backend/src/eneo/flows/ai_builder/ai_builder_edit_proposal.py:118`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:547`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_submission.py:599`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:480` | `ProposalSubmissionOwner` plus create/edit processors | Proposal submission owns raw LLM shape/tool-choice repair only; create/edit compilers own typed compile errors | Delete broad catch-to-repair; catch only known validation/contract exceptions | Invalid LLM payload still gets bounded repair; injected compiler bug does not call self-correction; telemetry separates model payload invalid from compiler bug |
| Create intent declares a strict schema but still normalizes and recovers invalid shapes after the fact. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py:259`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py:361`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py:412`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py:484`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_intent.py:615` | `ai_builder_proposal_intent.py` | `CreateFlowIntent` owns strict LLM-facing semantic contract; create compiler owns backend mechanics | Delete orphan output-field attachment first; challenge backend-key stripping and step-level assumption recovery unless telemetry proves need | Backend-owned keys and orphan objects rejected or self-corrected once; never silently patched |
| Post-compile normalizers silently rewrite topology, bindings, terminal artifacts, duplicate names, and incompatible fields. | `backend/src/eneo/flows/ai_builder/ai_builder_compiled_spec_preparation.py:47`, `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py:64`, `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py:141`, `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py:192`, `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py:448`, `backend/src/eneo/flows/ai_builder/ai_builder_step_transition_policy.py:802`, `backend/src/eneo/flows/ai_builder/ai_builder_create_dataflow.py:162` | compiled spec preparation, step transition policy, create dataflow | Create compiler/new-step compiler owns create topology; edit compiler owns edit transformations; runtime parser/validator rejects persisted invalid specs | Move create-only topology into create compiler; keep only idempotent migration normalizers with owner/deletion trigger | Compiled create output valid without generic repair; invalid authored spec rejected; remaining normalizer is idempotent and documented |
| Quality feedback patches validation prose with string heuristics. | `backend/src/eneo/flows/ai_builder/ai_builder_create_feedback.py:74`, `backend/src/eneo/flows/ai_builder/ai_builder_create_feedback.py:101`, `backend/src/eneo/flows/ai_builder/ai_builder_create_feedback.py:123` | `ai_builder_create_feedback.py` | Validator/critic issue codes carry model-safe remediation | Delete substring checks and string replacement; map structured issue codes | Tests assert issue-code-to-remediation, not full text matching |
| Planning state is documented as durable truth, but discovery/profile code still re-derives legacy answers. | `backend/src/eneo/flows/ai_builder/planning_state.py:1`, `backend/src/eneo/flows/ai_builder/ai_builder_discovery_profile_builder.py:214`, `backend/src/eneo/flows/ai_builder/ai_builder_discovery_profile_builder.py:452`, `backend/src/eneo/flows/ai_builder/ai_builder_user_question_metadata.py:49` | planning-state builder, discovery profile builder, user-question metadata | `PlanningState` / `PlanningStateBuilder` own durable slots; `DiscoveryProfile` is a read model | Merge duplicate answer derivation into planning-state projection; keep auxiliary adjudication only at input adapter boundary | Adding a slot requires one owner change; profile cannot diverge from planning state |
| Flow authoring/metadata tolerant reads may be legitimate legacy compatibility but need evidence and deletion triggers. | `backend/src/eneo/flows/flow_metadata.py:148`, `backend/src/eneo/flows/flow_metadata.py:262`, `backend/src/eneo/flows/flow_authoring_spec.py:122`, `backend/src/eneo/flows/flow_authoring_spec.py:164`, `backend/src/eneo/flows/flow_authoring_spec.py:219` | Flow metadata and authoring spec | Fail before write; migrations own known legacy shapes | Do not delete blindly if shipped data exists; require persisted-data evidence | Tests distinguish legacy migration tolerance from new-write validation |

## Recommended Fable Split

| Priority | Fable session | Exact scope |
|---:|---|---|
| 1 | Proposal repair boundary | `ai_builder_proposal_submission.py`, `ai_builder_proposal_repair.py`, `ai_builder_proposal_tool_contracts.py`, `ai_builder_tool_parsing.py`, `ai_builder_create_proposal.py`, `ai_builder_edit_proposal.py`, `ai_builder_proposal_intent.py`, `ai_builder_create_feedback.py`, `ai_builder_proposal_finalization.py`, proposal tests |
| 2 | Compiler/topology invalid-state prevention | `ai_builder_create_compiler.py`, `ai_builder_create_dataflow.py`, `ai_builder_new_step_compiler.py`, `ai_builder_step_transition_policy.py`, `ai_builder_compiled_spec_preparation.py`, `ai_builder_validator.py`, `ai_builder_edit_compiler.py`, `flow_authoring_spec.py`, runtime step parser, flow validators/tests |
| 3 | Planning state + JSONB/data-model durability | `planning_state.py`, `planning_state_builder.py`, `ai_builder_discovery_profile_builder.py`, `ai_builder_user_question_metadata.py`, `ai_builder_conversation_metadata.py`, `ai_builder_repo.py`, `ai_builder_domain_models.py`, `flow_jsonb_ownership.py`, `flow_metadata.py`, `flow_tables.py` |

If budget allows only one session, run session 1.
If budget allows four sessions, split session 3 into planning-state truth and JSONB/relational durability.

## JSONB Notes

| Field / area | Verdict | What would decide |
|---|---|---|
| `builder_sessions.planning_state_jsonb` | Keep JSONB; good typed full-snapshot use. | Move only if slots need cross-session query/audit/history. |
| `builder_sessions.conversation` | Keep short-term; likely relationalize to `builder_session_messages` if 50k users require audit, search, analytics, long conversations, pagination, or reduced row-lock contention. | Row growth, message-level queries, legal/audit requirements, pagination. |
| `builder_plans.proposal_json` | Keep proposal snapshot JSONB, but materialize stable list/filter fields if query evidence grows. | Repeated JSON-path queries in list/search/dashboard endpoints. |
| Flow step contracts/config/bindings | Keep JSONB; mode-specific sparse payload/contracts. | Extract only if fields become indexed query dimensions or analytics. |
| `flows.metadata_json.form_schema` | Keep if display/runtime payload; consider relational `flow_form_fields` if form fields become contract/search/permission/analytics objects. | Need to query by field, enforce DB uniqueness/options, audit changes, or API filter dimensions. |
| `flow_versions.definition_json` | Keep JSONB; immutable snapshots are good JSONB. | Extract only if version diff/search becomes first-class. |
| Runtime payloads/results/attempt provenance | Keep JSONB while statuses/tokens/provider/timestamps/FKs remain relational. | Extract fields used for filtering, billing, compliance, dashboards. |

## Tomorrow Implementation Candidates

1. Delete broad catch-to-repair in create/edit proposal processors.
2. Remove speculative create-intent payload recovery, starting with orphan output-field attachment.
3. Replace string-based create quality feedback patches with structured issue-code remediation.
4. Split post-compile normalizer into compiler-owned construction versus legacy compatibility only after Fable session 2.
5. Materialize `builder_plans` list fields only if JSON-path query evidence grows.
6. Collapse planning-state/discovery duplicate truth only after Fable session 3.

## Fable Follow-Up Questions

- Which repair belongs at the raw LLM/tool boundary and which should be deleted/moved?
- What contract narrowing would make invalid proposals hard to produce?
- Which normalizers are compatibility/migration shims with evidence and deletion triggers?
- Which JSONB fields are justified snapshots, and which are accumulating queryable data?
- Which first implementation slice removes the most debt without a broad rewrite?
