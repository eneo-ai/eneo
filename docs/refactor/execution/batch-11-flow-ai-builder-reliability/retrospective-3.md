# Batch 11.1a Retrospective — StepSkeleton Materialization

## TL;DR

1. Slice 11.1a adds the typed StepSkeleton materialization owner without
   changing proposal or compile behavior.
2. `StepSkeletonPlan` models backend-owned prefix/suffix mechanics plus
   repeatable semantic slots, so variable-length chains are not hardcoded.
3. Pattern-chain realization now consumes skeleton-owned defaults instead of
   owning backend-added chain templates itself.
4. Claude found and cleared the fixed-shape blocker before final validation.
5. 11.1b must wire the compiler to consume the skeleton and delete the duplicate
   mechanics helpers.

## Scope

Implemented:

- `StepSkeleton` and `StepSkeletonPlan` typed dataclasses
- deterministic `materialize_step_skeleton`
- legal policy tuple validation and runtime-upload ordinal guards
- skeletons for audio text/artifact, DOCX template fill, structured quality,
  comparison, linear text/document, and text-to-JSON flows
- skeleton-owned compiled chain templates and default structured-output fields
- focused StepSkeleton tests and compiler-mechanics equivalence tests

Not implemented:

- `compile_outline_to_create_draft` skeleton consumption
- skeleton fill/merge rules for user-authored semantic content
- typed architecture error surface
- critic invariant retargeting
- frontend/API behavior changes
- manual API smoke-suite scorecards

## Ownership

| Concept | Current owner | Decision |
|---|---|---|
| Skeleton contract and materialization | `backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py` | New canonical owner for typed skeleton plans and backend-owned step mechanics. |
| Pattern chain realization | `backend/src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py` | Kept narrow; it imports skeleton-owned defaults until 11.1b folds compilation into skeleton consumption. |
| Current compile mechanics helpers | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` | Preserved only until 11.1b to avoid mixing integration behavior into 11.1a. |
| Chain step tokens | `backend/src/intric/flows/ai_builder/pattern_registry.py` | Added `ChainStepToken` alias so skeleton fields use the registry vocabulary. |

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented 11.1a only; compile integration remains 11.1b. |
| Claude plan loop | pass | Revised plan reached `GREEN_LIGHT: yes`, minimum score `8`. |
| Claude implementation loop | pass | Fixed-shape blocker was accepted and revised; final verification reached green. |
| Canonical owner respected | pass | Skeleton ownership is in one narrow module; no compatibility alias was added. |
| Typed contracts | pass | Skeleton slots use dataclasses, closed literals, Flow enum values, and `ChainStepToken`. |
| Comment hygiene | pass | Added only intent-level docstrings/comments for slot expansion and create/edit policy differences. |
| Behavior unchanged | pass | The compiler is not wired to skeletons in this slice. |
| Tests protect behavior | pass | Tests validate legal tuple closure and parity with current compiler mechanics. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py -q` | Passed: `20 passed`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py -q` | Passed: `132 passed`. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py src/intric/flows/ai_builder/ai_builder_create_outline.py src/intric/flows/ai_builder/pattern_registry.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `7 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_step_skeleton.py backend/src/intric/flows/ai_builder/ai_builder_outline_pattern_chains.py backend/src/intric/flows/ai_builder/ai_builder_create_outline.py backend/src/intric/flows/ai_builder/pattern_registry.py backend/tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |

Broader `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` was
attempted and blocked by surfaces outside this slice: one server-action
assertion, missing local WeasyPrint native libraries (`libgobject-2.0-0`), and
import-linter source-module drift.

## Carry-Forward

| Item | Owner slice |
|---|---|
| Wire `compile_outline_to_create_draft` to consume `materialize_step_skeleton`. | 11.1b |
| Delete or move duplicate create-outline mechanics helpers after skeleton consumption lands. | 11.1b |
| Replace temporary equivalence tests with direct compiler-skeleton behavior tests. | 11.1b |
| Add skeleton fill/merge rules for semantic content. | 11.1b |
| Add typed architecture error and critic invariant classification. | 11.1c |
| Re-check single-step audio artifact semantic defaults once LLM fill is integrated. | 11.1b |

## Risk

The architecture is cleaner but not yet behavior-changing. Until 11.1b wires the
compiler to consume `materialize_step_skeleton`, the old create-outline helper
path and the new skeleton owner coexist. That coexistence is intentionally short
and has a named delete path.

## Confidence

High for 11.1a. Medium for the full 11.1 outcome until 11.1b removes the
duplicate mechanics path and proves audio-to-DOCX compiles through skeleton
materialization.
