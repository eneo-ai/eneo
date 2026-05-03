# Batch 11.2b Retrospective - Model Slot Resolver Runtime Overlay

## TL;DR

1. Slice 11.2b wires model slot classification into runtime PlanningState
   without adding another persisted resolver contract.
2. Discovery semantic adjudication now delegates to the same classifier core, so
   the old discovery-only parser/cache/result path is deleted instead of kept
   as compatibility.
3. The merge policy is intentionally conservative: explicit user answers,
   requirements summaries, and flow defaults beat model output.
4. Blocking discovery keeps the no-extra-LLM behavior through an explicit
   `allow_classification` gate.
5. Focused tests, Pyright, Ruff, import contracts, anti-slippage, and Claude
   verification are green.

## Scope

Implemented:

- shared `ai_builder_slot_classifier.py` with `ClassifiedSlot`,
  `SlotClassificationResult`, one canonical `slots/slot_name` JSON shape,
  stable prompt hashing, a bounded cache, and tenant-aware structured logs
- `build_runtime_planning_state()` as the async runtime owner for model
  classification before planner action-policy computation
- `merge_llm_resolved_slots()` as the sync PlanningState merge owner
- model overlay priority for missing, heuristic, and policy-default slots
- shared `UNKNOWN_SLOT_VALUE` and `NON_LLM_RESOLVABLE_SLOT_NAMES`
- planner-level blocking-discovery gate through `allow_classification=False`
- tests for classifier parsing, cache behavior, tenant log context, runtime
  gates, merge priority, non-LLM slots, and deterministic corpus baseline

Not implemented:

- provider-backed score run against the frozen 80-case corpus
- keyword-prior deletion
- production disagreement measurement
- public/session telemetry shape changes
- discovery question-id and PlanningState slot-name namespace unification

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented the approved runtime overlay slice and deferred provider scoring. |
| Claude plan loop | pass | Revised plan reached `GREEN_LIGHT: yes`, minimum score `8/10`. |
| Claude implementation loop | pass | Final parser-clean verification reached `GREEN_LIGHT: yes`, minimum score `9/10`. |
| Canonical owner respected | pass | Persisted slots remain `ResolvedSlot`; async model calls live in discovery runtime; sync merge lives in `planning_state_builder.py`. |
| Parallel path avoided | pass | The old `SemanticAdjudicationResult` / `SemanticAdjudicationSignal` path and old JSON shape are not preserved. |
| Typed contracts | pass | Classifier output is a frozen dataclass contract and merge writes typed `ResolvedSlot(source="model")`. |
| Comment hygiene | pass | Source comments are limited to non-obvious ownership/cache decisions; no tool, session, or plan comments were added. |
| Behavior tests | pass | Tests cover canonical shape rejection, illegal value filtering, cache reuse, model gates, merge priority, non-LLM exclusions, and blocking-discovery behavior. |
| Broader suite | pass | Focused AI Builder source/test suite passed with existing unrelated warnings. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_slot_classifier.py tests/unittests/flows/ai_builder/test_ai_builder_discovery_runtime.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_semantic_adjudication.py tests/unittests/flows/ai_builder/test_ai_builder_slot_vocabulary.py tests/unittests/flows/ai_builder/test_ai_builder_planner.py tests/unittests/flows/ai_builder/test_discovery_flow.py tests/unittests/flows/ai_builder/test_ai_builder_understanding_goldens.py tests/integration/flows/ai_builder/benchmark/test_slot_resolver_corpus.py -q` | Passed: `129 passed`, 16 existing warnings from unrelated deprecations. |
| `cd backend && uv run pyright <11.2b touched source/test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.2b touched source/test files>` | Passed. |
| `cd backend && uv run ruff format --check <11.2b touched source/test files>` | Passed: `18 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed. |
| Added-line slop grep for source/test `deprecated`, `legacy`, `backwards compatibility`, source-control/session/tooling comments, and TODO/FIXME markers | Passed with no matches. |

## Evidence

| Concern | Evidence | Decision |
|---|---|---|
| Shared classifier contract | `backend/src/intric/flows/ai_builder/ai_builder_slot_classifier.py:24`, `:39`, `:131`, `:202` | One classifier owns the transient result type, LLM call, parser, and prompt hash. |
| Runtime async owner | `backend/src/intric/flows/ai_builder/ai_builder_discovery_runtime.py:75`, `:98`, `:115` | Runtime builds deterministic state first, calls the classifier only when gated in, then overlays accepted slots. |
| Conservative merge | `backend/src/intric/flows/ai_builder/planning_state_builder.py:164`, `:213` | Sync merge validates legal slots/values and only replaces missing, heuristic, or allowed policy-default slots. |
| Non-LLM slots | `backend/src/intric/flows/ai_builder/ai_builder_slot_vocabulary.py:26` | DOCX/PDF generation mode stays out of model guessing. |
| Blocking discovery | `backend/src/intric/flows/ai_builder/ai_builder_planner.py:554`, `:562` | Planner passes `allow_classification=False` when backend follow-up should block proposal work. |
| Old shape rejected | `backend/tests/unittests/flows/ai_builder/test_ai_builder_slot_classifier.py:27` | Test asserts the former `signals/question_id` shape does not produce slots. |
| Weak-slot upgrade | `backend/tests/unittests/flows/ai_builder/test_ai_builder_discovery_runtime.py:93` | Runtime test verifies model high confidence can replace a policy default. |
| Protected evidence | `backend/tests/unittests/flows/ai_builder/test_planning_state_builder.py:293` | Merge tests pin explicit/summary/default protection. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Provider-backed evaluation against the frozen 80-case corpus before claiming the `>= 0.85` target. | 11.2c or next resolver eval slice |
| Keyword-prior deletion criterion and real disagreement measurement. | Later 11.2 follow-up |
| Discovery question-id and PlanningState slot-name namespace unification. | Future cleanup |
| Lift the weak-source set into one named owner if another weak slot source is introduced. | Future slot-source extension |

## Risk

The model overlay now runs in live runtime planning when a client/model is
available and classification is allowed. The blast radius is bounded by legal
slot/value filtering, confidence rules, non-LLM slot exclusions, and a merge
policy that cannot displace explicit user or flow evidence.

The frozen corpus still measures the deterministic sync builder, not the model
runtime path. That is intentional for this slice, but the resolver target should
not be claimed until a provider-backed evaluation is recorded.

## Confidence

High for the runtime overlay and deletion of the duplicate discovery parser
path. The final Claude verification scored the slice `9/10`, the focused tests
passed, and the remaining items are measurable follow-ups rather than commit
blockers.
