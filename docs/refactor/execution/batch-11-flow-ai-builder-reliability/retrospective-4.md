# Batch 11.1b Retrospective — StepSkeleton Fill Integration

## TL;DR

1. Slice 11.1b wires create-outline compilation to `StepSkeletonPlan.compose`.
2. The old pattern-chain realizer file and create-outline `_derive_step_*`
   mechanics path are deleted.
3. Generated DOCX/PDF paths now use backend terminal artifact suffixes instead
   of letting the last semantic step emit the artifact directly.
4. Focused validation is green; the broader AI Builder unit suite still fails
   on known unrelated/environmental surfaces.
5. 11.1c should add the architecture error surface and edit-path preserve/reject
   rules, and should watch skeleton module size.

## Scope

Implemented:

- `StepSkeletonPlan.compose`
- typed `StepSkeletonComposition` and `StepSkeletonOutputTypeDrift`
- create-outline skeleton materialization and composition
- drift logging for explicit semantic output-type conflicts
- generated artifact terminal suffixes for linear/audio DOCX/PDF paths
- audio aggregate fan-in on the terminal artifact slot
- locked-policy guard for backend-fixed slots
- deletion of `ai_builder_outline_pattern_chains.py`
- registry test for compiled chain skeleton materializers

Not implemented:

- edit-path mechanic preservation/rejection
- `AIBuilderArchitectureError`
- critic invariant architecture/semantic/hybrid classification
- additional drift categories beyond output-type drift
- frontend/API changes

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented 11.1b only. |
| Claude plan loop | pass | Revised plan reached green in iteration 2. |
| Claude implementation loop | pass | Final parser-clean verification reached `GREEN_LIGHT: yes`, minimum score `8/10`. |
| Canonical owner respected | pass | `StepSkeletonPlan.compose` is the final mechanics resolver. |
| Parallel path deleted | pass | `ai_builder_outline_pattern_chains.py` removed; create-outline helpers deleted. |
| Typed contracts | pass | Composition/drift events are typed dataclasses. |
| Comment hygiene | pass | Only short intent docstrings were added to public composition surfaces. |
| Behavior tests | pass | Audio DOCX, audio aggregate fan-in, JSON intermediate, drift logging, fallback append, and locked slots are covered. |
| Broader suite | blocked | Fails on known unrelated/environmental failures listed below. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py -q` | Passed: `140 passed`. |
| `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed. |
| `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_step_skeleton.py src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_step_skeleton.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_pattern_registry.py` | Passed: `5 files already formatted`. |
| `cd backend && uv run lint-imports --no-cache` | Passed: 3 contracts kept, 0 broken. |
| `git diff --check -- <11.1b touched paths>` | Passed. |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean`. |
| `cd backend && uv run pytest tests/unittests/flows/ai_builder -q` | Failed: `6 failed, 1685 passed`. Known failures are one server-action wording assertion, four WeasyPrint native library failures for `libgobject-2.0-0`, and `.importlinter` source-module drift. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Add typed architecture error surface that bypasses repair. | 11.1c |
| Classify critic invariants as architecture, semantic, or hybrid. | 11.1c |
| Implement edit-path fill/preserve/reject mechanics. | 11.1c |
| Split `ai_builder_step_skeleton.py` if 11.1c adds substantial compose/materializer code. | 11.1c |
| Generalize `StepSkeletonOutputTypeDrift` only if more drift classes are needed. | 11.1c |
| Resolve known broader-suite failures if they become part of the active slice. | Separate cleanup |

## Risk

The main behavior change is intentional: generated DOCX/PDF flows now get a
backend terminal artifact step instead of making the final LLM-authored semantic
step emit the artifact directly. This improves reviewability and makes Flow
mechanics visibly backend-owned, but it changes step counts for some generated
artifact plans.

The remaining architecture risk is file size. `ai_builder_step_skeleton.py` is a
deep module with one canonical responsibility, but 11.1c should split
materializers or composition before adding another large policy block.

## Confidence

High for 11.1b. Focused tests, static checks, import-linter, anti-slippage, and
Claude final verification are green. Broader unit-suite failures are real but
outside this slice.
