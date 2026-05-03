# Batch 11.5a Retrospective - Planner Structured Output Rail

## TL;DR

1. Slice 11.5a adds a typed provider-capability rail for AI Builder planner JSON turns.
2. `TenantModelAdapter` / `CompletionService` own provider capability; AI Builder consumes one precomputed decision.
3. Strict-schema-capable providers are downgraded to `json_object` while `PlannerOutput` remains incompatible with strict JSON schema.
4. Main and chained planner calls reuse one response-format selection; proposal tool-call prompts stay separate.
5. Validation passed, including full AI Builder unit and integration suites, and Claude green-lit the revised implementation.

## Result

| Area | Outcome |
|---|---|
| Capability owner | Added `tenant_model_capabilities.py` with typed modes, sources, decision invariants, LiteLLM probes, and unsupported fallback construction. |
| Adapter/service API | `TenantModelAdapter` resolves structured-output capability and `CompletionService` exposes the typed async method. |
| Planner selection | Added `ai_builder_response_format.py` to select strict schema, JSON object, or prompt validation from one decision. |
| Strict-schema honesty | Current `PlannerOutput` blockers are detected from the live schema and force `json_object` until the contract is cleaned. |
| Planner call path | Primary and chained planner turns use `_build_planner_litellm_kwargs(...)` with the same `PlannerResponseFormatSelection`. |
| Telemetry | Planner metrics emit seven canonical structured-output fields and no old JSON-mode bridge fields. |
| Proposal separation | Proposal tool-call prompts do not receive planner `response_format` kwargs. |

## Acceptance

| Criterion | Status | Evidence |
|---|---|---|
| Capability decision is typed and immutable. | pass | `StructuredOutputCapabilityDecision` is frozen, slotted, and validates mode/source/evidence consistency. |
| Provider capability has one owner. | pass | AI Builder does not call LiteLLM metadata directly; the path is capability owner to adapter to completion service. |
| Strict schema is not faked. | pass | `planner_output_strict_schema_blockers()` records live schema blockers and downgrades to `json_object`. |
| One decision feeds the planner turn. | pass | `PreparedMessageContext` carries the decision; `send_message` builds one selection and passes it through. |
| Chained dispatch reuses the selection. | pass | `test_send_message_reuses_one_planner_response_format_selection_for_chain` asserts object identity. |
| Proposal tool calls stay orthogonal. | pass | Proposal processor test asserts no planner `response_format` kwarg is sent. |
| No compatibility path for unreleased Flow AI behavior. | pass | Old planner JSON-mode telemetry keys were removed instead of carried forward. |

## Validation

| Command | Result |
|---|---|
| `uv run pytest tests/unit/test_tenant_model_capabilities.py tests/unit/test_tenant_model_adapter_prepare_kwargs.py tests/unittests/flows/ai_builder/test_ai_builder_response_format.py tests/unittests/flows/ai_builder/test_ai_builder_service.py::TestPlannerContextPreparation tests/unittests/flows/ai_builder/test_ai_builder_planner_send_message.py tests/unittests/flows/ai_builder/test_ai_builder_parse_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_router.py -q` | Passed: `164 passed`. |
| `uv run pytest tests/unittests/flows/ai_builder -q` | Passed: `1761 passed, 4 skipped`, 12 existing warnings. |
| `uv run pytest tests/integration/flows/ai_builder -q` | Passed: `93 passed, 20 deselected`, 16 existing warnings. |
| `uv run pyright <11.5a touched source and test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `uv run ruff check <11.5a touched source and test files>` | Passed. |
| `uv run ruff format --check <11.5a touched source and test files>` | Passed. |
| `uv run lint-imports --no-cache` | Passed: 3 import contracts kept. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed. |
| Claude final verification | Passed: `green`, minimum score `8`. |

## Follow-Ups

| Item | Owner |
|---|---|
| Make `PlannerOutput` strict-schema compatible or record why strict schema is not a maintainable fit. | 11.5b |
| Extend the typed rail to `outline_flow`, `edit_flow`, and parse repair only where the output contract is a typed JSON object. | 11.5b |
| Verify actual tenant/model Anthropic Haiku behavior in a live provider smoke. | 11.5b / provider eval |
| Evaluate the pre-existing `resolve_planner_params` introspection hedge separately. | Later Batch 11 cleanup |

## Risk

| Risk | Mitigation |
|---|---|
| LiteLLM metadata may differ across aliases or custom providers. | Capability evidence is logged; live provider smoke is carried into 11.5b. |
| Strict-schema branch could remain unreachable. | Blocker tests pin the current reason; 11.5b owns contract cleanup. |
| Planner structured-output kwargs could leak into proposal tool calls. | Proposal processor regression asserts no `response_format` kwarg. |
| Chained planner turn could drift from primary planner kwargs. | Identity and direct chained-dispatch tests cover both levels. |
| Telemetry consumers could expect old JSON-mode keys. | Flow AI Builder is unreleased; the new structured-output keys are the canonical contract. |

Confidence: high.
