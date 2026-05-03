# Batch 11.1d Retrospective — Edit-Path Mechanics

## TL;DR

1. Slice 11.1d closes the edit-path fill/preserve/reject mechanics carry-forward
   from 11.1c.
2. Create and edit add operations now share one per-new-step mechanics validator.
3. Edit proposals fill only missing first-step runtime upload mechanics and
   preserve explicit user-authored runtime choices.
4. Explicit invalid edit mechanics return validation feedback, not architecture
   errors or hidden compiler rewrites.
5. Focused validation and Claude verification are green; manual/API smoke remains
   part of the parent 11.1 success gate.

## Scope

Implemented:

- shared new-step mechanics validator
- create validator reuse of that shared owner
- edit-only runtime upload fill pass
- edit proposal cleanup/fill/validate ordering
- edit add mechanics validation by resolved insert index
- edit modify-patch output-mode conflict rejection
- modify-patch output-mode derivation through the existing create derivation owner
- focused behavior tests for fill, validation, compiler derivation, and proposal feedback

Not implemented:

- full edit-path skeleton materialization
- automatic rewiring of existing shifted `flow_input` steps
- manual local API smoke execution
- broad AI Builder suite cleanup outside the touched mechanics path

## Checklist

| Check | Result | Notes |
|---|---|---|
| Plan adherence | pass | Implemented the approved 11.1d edit-path mechanics plan. |
| Claude plan loop | pass | Iteration 2 reached `GREEN_LIGHT: yes`. |
| Claude implementation loop | pass | Iteration 3 reached `GREEN_LIGHT: yes`, minimum score `8/10`. |
| Canonical owner respected | pass | `validate_new_step_mechanics` owns per-new-step mechanics shared by create and edit. |
| Parallel path avoided | pass | Edit modify output-mode derivation calls `derive_new_step_output_mode` instead of duplicating enum matching. |
| Typed contracts | pass | Validation uses existing typed draft/enums and typed result contracts. |
| Comment hygiene | pass | No new source comments narrate the plan, tooling, or obvious control flow. |
| Behavior tests | pass | Tests cover fill defaults, explicit preservation, shared edit validation, compiler derivation, and proposal feedback. |
| Broader suite | not run | Focused validation covers the touched behavior; previous broader-suite limitations remain outside this slice. |

## Validation

| Command | Result |
|---|---|
| `cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_mechanics.py tests/unittests/flows/ai_builder/test_ai_builder_edit_normalizer.py tests/unittests/flows/ai_builder/test_ai_builder_edit_validator.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_create_dataflow.py tests/unittests/flows/ai_builder/test_ai_builder_materialization_bridge.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py -q` | Passed: `239 passed`, one existing Starlette multipart warning. |
| `cd backend && uv run pyright <11.1d touched source/test files>` | Passed: `0 errors, 0 warnings, 0 informations`. |
| `cd backend && uv run ruff check <11.1d touched source/test files>` | Passed. |
| `cd backend && uv run ruff format --check <11.1d touched source/test files>` | Passed: `10 files already formatted`. |
| `git diff --check -- <11.1d touched paths>` | Passed. |
| Claude implementation verification | Passed: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`. |

## Carry-Forward

| Item | Owner slice |
|---|---|
| Manual/API audio-to-DOCX smoke gate. | 11.1 success gate |
| If output-mode derivation needs more fields, extract a narrower derivation core and have create/edit call it. | Future mechanics cleanup |
| If another operation pass appears, consider one shared operation walker. | Future edit-path cleanup |
| Automatic shifted-first-step rewiring, if needed by manual edit smoke tests. | Future edit-path skeleton work |

## Risk

The edit compiler now derives omitted output mode for modified existing steps.
That is intentional for stale audio/text and template-fill mechanics, and focused
tests cover transcribe-only derivation, template-fill DOCX preservation, and
DOCX-to-PDF delivery-mode reconstruction.

The shared validator increases enforcement on edit add operations when current
steps are available. Invalid user-authored mechanics now fail earlier as
validation feedback. That should reduce repair loops for backend-owned
mechanics while keeping architecture errors reserved for backend failures.

## Confidence

High for the implemented edit-path mechanics. The code has one shared validation
owner, an edit-only fill owner, and focused tests from proposal parsing through
compiler output. Claude's final implementation pass was green, and the
non-blocking test questions were answered before commit.
