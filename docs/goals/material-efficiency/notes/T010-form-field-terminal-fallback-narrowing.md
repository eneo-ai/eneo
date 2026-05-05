# T010 Form Field Terminal Fallback Narrowing

## Result

Done.

## Problem

The live C2 case showed that a runtime form field can be declared but routed too late. In that case, `fokusområde` appeared only at the terminal PDF step even though the user explicitly required it to steer the intermediate risk analysis step.

The root cause was not missing template compilation. The compiler already inserts `uses_form_fields` into `input_bindings.question`. The problem was that `compile_outline_to_create_draft` silently attached every otherwise-unreferenced form field to the final step. That made `find_unused_form_fields`, `lint_unused_form_fields`, and the critic invariant believe the field was used, so the planner omission was hidden instead of repaired.

## Change

Changed `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` so `_attach_unreferenced_form_fields_to_final_step` only applies when the outline has one semantic step.

For multi-step flows, declared-but-unreferenced form fields now remain unused. That lets the existing canonical usage predicate and validator/critic path report `unused_form_field` instead of laundering the field into a terminal document/text step.

Removed the terminal fallback diagnostic helper because the multi-step terminal fallback it described no longer exists.

## Tests

Updated `backend/tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`:

- A multi-step text flow with an unused `priority` field leaves it unused and emits an `unused_form_field` warning.
- A multi-step PDF-renderer flow with an unused `focus_area` field leaves it unused and emits an `unused_form_field` warning.
- A single semantic-step PDF flow still binds the declared field to the generated terminal renderer step, preserving the simple-flow convenience.
- Existing explicit create/edit form-field references still bind once per intended step.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py -q`  
  `6 passed`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_compiler.py -q -k 'form_field or input_field or runtime_input_field'`  
  `7 passed, 101 deselected`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_form_field_usage.py -q`  
  `8 passed`
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`  
  `All checks passed!`
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`  
  `2 files already formatted`
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_create_outline.py tests/unittests/flows/ai_builder/test_ai_builder_form_field_lifecycle.py`  
  `0 errors, 0 warnings, 0 informations`
- `python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --case C2 --runs 1 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260505-223500-t010-c2-targeted`  
  `C2 run 1: applied flow=05b26073-c54d-43ed-a5ee-292bae3ce24a`

## Peer Review

Claude iteration 1 blocked the earlier plan and correctly identified terminal fallback laundering as the higher-ROI root cause than adding planner token heuristics.

Claude iteration 2 returned `GREEN_LIGHT: yes`, `VERDICT: green`, `MIN_SCORE: 8`. Two non-blocking suggestions were incorporated before commit:

- Add a direct critic-invariant assertion for `form_fields_declared_must_be_referenced`.
- Add a short invariant comment explaining why the one-semantic-step fallback is safe while multi-step fallback is not.

## Scope Notes

This does not make the planner infer that `fokusområde` belongs on the risk step. It makes the current failure visible to existing linter/critic repair instead of hiding it at the terminal step. A later slice should improve planner instructions and repair behavior once this lower-level masking behavior is removed.

The commit also carries forward a pre-existing local assertion update in `test_intermediate_form_field_use_flows_through_structured_previous_field`: the compiled final step has no `input_contract` after targeted structured-field binding. That expectation was already present in the dirty worktree before T010; keeping it lets the form-field lifecycle test file run green as a whole.

The targeted post-fix C2 live rerun improved the specific failure: `focus_area` reached the risk JSON step through explicit `input_bindings.question`. It is not a full C2 pass. `organization_name` and `report_period` were still declared without useful downstream bindings, and one composer still used `all_previous_steps`.
