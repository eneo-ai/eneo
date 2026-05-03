# Batch 11.5a Claude Reconciliation - Planner Structured Output Rail

## TL;DR

1. Claude rejected the first structured-output plan because strict schema feasibility, capability ownership, chained planner behavior, and telemetry were not precise enough.
2. The accepted plan scopes 11.5a to provider capability plus planner JSON turns, and defers proposal tool-call expansion.
3. Implementation added a typed provider-capability owner, planner response-format selector, and behavior tests across strict, JSON object, and prompt-validation paths.
4. Claude green-lit the initial implementation with follow-ups; Codex fixed the typed-dependency hedge, removed old JSON-mode telemetry keys, and added a same-selection chain test.
5. Claude green-lit the revised implementation with minimum score `8`.

## Plan Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 1 | `.codex/artifacts/claude-peer-loop-batch-11-5-structured-output-rail-plan-20260503T072546Z.md` | `changes_required` | `no` | 6 | Tighten strict-schema feasibility, provider override scope, chained planner selection, proposal separation, and telemetry. |
| 2 | `.codex/artifacts/claude-peer-loop-batch-11-5-structured-output-rail-revised-plan-20260503T073127Z.md` | `green` | `yes` | 8 | Approved the revised 11.5a planner-only slice. |

The earlier artifact `.codex/artifacts/claude-peer-loop-batch-11-5-structured-output-rail-plan-20260503T072118Z.md` was a failed resume attempt and did not influence the implementation direction.

## Accepted Plan Findings

| Finding | Resolution |
|---|---|
| `PlannerOutput` might not satisfy strict structured-output schema rules. | Codex inspected the live schema and found union/default/optional-object blockers; 11.5a downgrades strict-capable providers to `json_object`. |
| Structured-output capability should not be queried directly from AI Builder. | Added `tenant_model_capabilities.py` and delegated through `TenantModelAdapter` and `CompletionService`. |
| Explicit model override policy was speculative. | No override surface was added in 11.5a. |
| Proposal tool calls should not be treated as a fallback rung. | Tool calls remain orthogonal; 11.5a does not send planner `response_format` into proposal prompts. |
| Chained planner calls must use the same decision as primary planner calls. | `send_message` builds one selection and passes it through the chained server-action path. |

## Final Shape

| Concept | Owner |
|---|---|
| Provider structured-output capability | `backend/src/intric/completion_models/infrastructure/tenant_model_capabilities.py`. |
| Tenant model LiteLLM parameter support | `TenantModelAdapter`, using the shared capability helper. |
| Completion-service capability handoff | `CompletionService.resolve_structured_output_capability`. |
| Planner response-format selection | `backend/src/intric/flows/ai_builder/ai_builder_response_format.py`. |
| Planner kwargs and telemetry | `AIBuilderPlanner`, via `_build_planner_litellm_kwargs` and `_structured_output_log_fields`. |
| Proposal tool-call behavior | Existing proposal processor; no planner response-format kwargs are injected. |

## Implementation Review

| Iteration | Artifact | Verdict | Green light | Minimum score | Outcome |
|---:|---|---|---|---:|---|
| 3 | `.codex/artifacts/claude-peer-loop-batch-11-5a-structured-output-implementation-20260503T075748Z.md` | `GREEN_LIGHT` | `yes` | 7.5 | Approved ship-with-follow-ups; identified three high-ROI cleanup items. |
| 4 | `.codex/artifacts/claude-peer-loop-batch-11-5a-structured-output-implementation-follow-up-20260503T080716Z.md` | `green` | `yes` | 8 | Verified the follow-up cleanup and recommended commit. |

Accepted implementation findings:

| Finding | Resolution |
|---|---|
| `AIBuilderService.resolve_planner_structured_output_capability` used runtime `getattr` / `isawaitable` against a typed dependency. | Replaced with a direct async call to `CompletionService.resolve_structured_output_capability`. |
| Planner metrics had redundant old JSON-mode keys. | Removed `response_format_requested`, `drop_params`, and `json_mode_requested`; the structured-output fields are canonical. |
| The chained path lacked a same-selection assertion. | Added an identity-based `send_message` regression plus the direct chained-dispatch kwargs test. |

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

## Carry-Forward

| Item | Owner |
|---|---|
| Decide whether `PlannerOutput` should be refactored into strict-schema-compatible shape. | 11.5b |
| Extend the typed structured-output rail to proposal and parse-repair contracts only after each contract proves it benefits from the rail. | 11.5b |
| Run a live provider smoke for the tenant/model aliases that will actually be used. | 11.5b / provider eval |
| Review the pre-existing `resolve_planner_params` runtime introspection separately. | Later Batch 11 cleanup |

Confidence: high.
