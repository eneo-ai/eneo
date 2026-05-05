# T008 Form-Field Terminal Diagnostic

## Result

Added a compiler-owned diagnostic for a live-eval form-field routing risk without changing generated flow behavior.

## Problem

Live case C2 applied successfully, but the generated flow only surfaced `focus_area` in the terminal PDF binding even though the prompt required the focus area to steer the risk-analysis step. Claude rejected a broad critic invariant because the same flow also had legitimate final-heading fields (`organization_name`, `report_period`) that may belong at the document renderer. A structural critic rule would have produced false positives without semantic field classification.

## Change

- Kept the existing fallback behavior in `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py`.
- Added `ai_builder_form_fields_attached_to_document_terminal` at `info` level when `_attach_unreferenced_form_fields_to_final_step` attaches otherwise unreferenced form fields to a DOCX/PDF/template document terminal and there is at least one prior compositional step.
- Logged structured fields as native values, including `form_field_names: list[str]`, final step metadata, prior content count, and step count.
- Added positive and negative tests around the diagnostic in `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`.

## Red Evidence

`uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py -q -k renderer_terminal_form_field_fallback_logs_diagnostic`

Initial result: failed with `StopIteration` because no diagnostic existed.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py -q -k 'renderer_terminal_form_field_fallback_logs_diagnostic or declared_input_field_without_step_use_attaches_to_final_step or single_step_renderer_form_field_fallback_does_not_log_diagnostic'`
  - `3 passed, 3 deselected`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'form_field or input_field or runtime_input_field'`
  - `7 passed, 101 deselected`
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`
  - `All checks passed`
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`
  - `2 files already formatted`
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`
  - `0 errors, 0 warnings, 0 informations`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py -q`
  - `5 passed, 1 failed`
  - Failure was the known pre-existing `test_intermediate_form_field_use_flows_through_structured_previous_field` input-contract assertion.

## Pre-Existing Failure Check

I stashed only the two touched files and ran:

`uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py::test_intermediate_form_field_use_flows_through_structured_previous_field -q`

The same assertion failed on `HEAD`: `compiled.steps[-1].input_contract is None` while the test expected the previous output contract. The diagnostic diff does not touch that `compile_create_draft` path.

## Claude Review

- Iteration 1 rejected a broad critic invariant and recommended diagnostics first.
- Iteration 2 rejected warning-level logging, CSV-shaped log fields, missing negative tests, and missing proof for the unrelated failing test.
- Iteration 3 returned `GREEN_LIGHT: yes` for the narrowed diagnostic slice.

Artifacts:

- `.codex/artifacts/claude-peer-loop-t008-form-field-routing-plan-20260505T194934Z.md`
- `.codex/artifacts/claude-peer-loop-t008-form-field-routing-implementation-20260505T195724Z.md`
- `.codex/artifacts/claude-peer-loop-t008-form-field-routing-implementation-v2-20260505T200314Z.md`

## Follow-Ups

- Consolidate renderer predicates currently split across `ai_builder_create_outline.py`, `ai_builder_create_dataflow.py`, and `ai_builder_critic_invariants.py`.
- Track and fix the pre-existing `test_intermediate_form_field_use_flows_through_structured_previous_field` input-contract assertion separately.
- Use the new diagnostic in future live evals to measure how often fallback-attached terminal form fields indicate real material-routing failures before adding policy.
