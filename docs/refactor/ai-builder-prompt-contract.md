# AI Builder Prompt Contract

## TL;DR

- `ai_builder_prompts.py` owns the planner system prompt assembly boundary.
- `ai_builder_knowledge_pack_protocol.py` owns the planner JSON protocol text.
- `ai_builder_create_outline.py` and `ai_builder_edit_tool_schema.py` own final proposal tool schemas.
- `ai_builder_repair.py` owns semantic and parse-repair prompt obligations for planner JSON.
- Tests must pin stable contract anchors, not full prompt snapshots.

## Canonical Owners

| Contract surface | Canonical owner | Test owner |
|---|---|---|
| System prompt assembly | `backend/src/intric/flows/ai_builder/ai_builder_prompts.py` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_prompts.py` |
| Planner JSON protocol | `backend/src/intric/flows/ai_builder/ai_builder_knowledge_pack_protocol.py` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_knowledge_pack.py` |
| Create proposal tool | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_knowledge_pack.py` |
| Edit proposal tool | `backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_knowledge_pack.py` |
| Semantic and parse repair | `backend/src/intric/flows/ai_builder/ai_builder_repair.py` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_repair.py` |
| Proposal tool repair | `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` | `backend/tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py` |

## Prompt Inputs

The prompt assembly boundary may receive these inputs:

- mode: create or edit
- current flow context for edit mode
- available models, with exact model `ref` values
- available knowledge bases, with exact knowledge `ref` values
- available MCP servers and tools, with exact server/tool `ref` values
- confirmed requirements and requirements version
- action policy for the current turn
- UI language
- planner hints
- attachment context
- planning state block and `base_planning_state_version`

## Planner Obligations

The planner JSON contract is intentionally separate from final plan proposal tools.

- The planner response is one raw JSON object, with no prose, markdown fences, or function calls.
- The JSON object includes `planning_state_delta.base_planning_state_version`.
- The JSON object includes `planner_action.kind`.
- The allowed planner action kinds are `ask_question`, `confirm_requirements`, and `commit_architecture`.
- The planner must not embed final plan proposals in planner JSON.
- In create mode, the final proposal must go through `outline_flow`.
- In edit mode, the final proposal must go through `edit_flow`.
- Knowledge, model, and MCP references must use exact `ref` values from the server-rendered context.
- Prompt contexts render references as `ref=` values; the LLM must copy those exact `ref` values, not labels.
- `architecture_commit` is server-derived. The planner should emit `architecture_commit: null` when committing architecture and must not invent hashes, timestamps, UUIDs, or other mechanical fields.

## Repair Obligations

Semantic and parse repair are separate contracts.

- Semantic repair uses rejection detail, not internal rejection code vocabulary.
- Semantic repair must preserve the committed architecture body once pinned.
- Parse repair has a separate retry budget from semantic repair.
- Parse repair asks for a single raw JSON object.
- Parse repair says: Do NOT wrap the JSON in markdown code fences.
- Parse repair says: Do NOT add prose before or after the JSON.
- Proposal tool repair keeps tool-call grouping intact and uses the proposal repair retry budget.
- Repair failure diagnostics must be typed and client-safe; raw prompt/body details belong in sanitized logs, not public API responses.

## Stable Test Anchors

The prompt-contract artifact test owns these stable anchors:

| Anchor | Must appear in artifact | Must appear in owner |
|---|---:|---:|
| `base_planning_state_version` | yes | yes |
| `outline_flow` | yes | yes |
| `edit_flow` | yes | yes |
| exact `ref` values | yes | yes |
| `architecture_commit: null` | yes | yes |
| single raw JSON object | yes | yes |
| Do NOT wrap | yes | yes |

Do not snapshot full prompts. Prompt text is allowed to improve, but these anchors are contractual.
