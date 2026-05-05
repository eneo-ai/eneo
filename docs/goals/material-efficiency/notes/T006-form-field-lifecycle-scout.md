# T006 Form-Field Lifecycle Scout

## Result

Blocked for implementation in this tranche until live eval or product evidence shows a concrete failure mode.

## Evidence Reviewed

- `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` drops server-derived runtime hints unless the planner references them via `uses_input_fields`.
- `backend/src/intric/flows/ai_builder/ai_builder_new_step_compiler.py` compiles referenced `uses_form_fields` into `input_bindings.question`, so runtime fields become explicit underlag when a step declares that it uses them.
- `backend/src/intric/flows/ai_builder/ai_builder_validation_quality.py` warns for unused compiled form fields through `find_unused_form_fields`.
- `backend/src/intric/flows/ai_builder/ai_builder_form_field_usage.py` checks instructions, input bindings, and output config for form-field references.
- Existing create compiler tests cover dropping ignored hints, keeping referenced hints, wiring referenced fields into underlag, and avoiding unused fields.

## Decision

Do not add a production classifier for "content material field" vs "behavior/style-only field" yet.

The distinction is real, but implementing it now would require guessing from names such as `tone`, `audience`, `focus`, or `report_type`. That would add brittle language/domain heuristics and could break valid flows where those values genuinely need to be visible to a step.

## Next Evidence Needed

Use live eval cases C2, C4, and C5 to find concrete failures:

- a form field is declared but never consumed
- a field needed by an intermediate step only appears in the final step
- a field is hard-coded into instructions instead of bound as runtime material
- style/tone fields bloat source-material bindings when they should only steer behavior

Promote any confirmed failure into deterministic tests before production changes.

## Verification

No code changed in this task. T006 is intentionally skipped/blocked by the existing `stop_if` condition: implementation would require a UI/product decision or live-eval evidence before coding.
