# T013 Runtime Field Absence Polarity

## Problem

C1 live logs showed the proposal repair loop demanding named runtime input fields even though the user explicitly said `Inmatningsfält behövs inte.` The confirmed requirements also represented the user's answer as `Metadata vid körning: Inga extra fält`, but the shared runtime input-field detector did not treat `extra fält` / `extra fields` as an absence trigger and did not understand post-trigger negation such as `Input fields are not needed`.

## Why It Matters

This is a general Flow AI Builder planning correctness issue, not a C1 prompt issue. If explicit absence is missed, downstream planner pattern signals can infer that a rich document workflow needs form fields and the critic/repair loop can push the model toward invented runtime fields. That makes flows less faithful to the user's contract and creates unnecessary form-field material.

## Canonical Owner

`backend/src/intric/flows/ai_builder/ai_builder_runtime_input_fields.py` is the canonical owner for runtime input-field intent and absence semantics. Existing consumers already route through that owner:

- `ai_builder_planner_pattern_signals.py` uses `runtime_input_fields_declared_absent(...)` to set `derive_from_input_only` and suppress inferred `needs_form_fields`.
- `ai_builder_critic_invariants.py` uses those planner pattern signals before firing `rich_workflow_requires_form_fields`.
- Planning state uses `infer_runtime_metadata_slot(...)` to resolve `runtime_metadata_fields`.

No prompt-specific or C1-specific branch was added.

## Change

- Added `extra fält`, `extra falt`, and `extra fields` to runtime metadata absence triggers.
- Added post-trigger absence polarity for forms like `Inmatningsfält behövs inte`, `Inmatningsfält krävs inte`, `Input fields are not needed`, and `Input fields are not required`.
- Preserved positive form-field requests such as `Input fields are required, not optional`.
- Added behavior tests covering the parser, planning-state slot inference, and critic behavior for an audio-to-DOCX flow with explicit no input fields.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py -q`
  - `144 passed`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder -q`
  - `1942 passed, 4 skipped, 12 warnings`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
  - `All checks passed!`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
  - `4 files already formatted`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_ai_builder_runtime_input_fields.py tests/unittests/flows/ai_builder/test_planning_state_builder.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py`
  - `0 errors, 0 warnings, 0 informations`

## Live Evaluation

- Targeted C1 after the fix:
  - `/tmp/material-efficiency-live-eval/20260505-233516-t013-c1-runtime-field-absence-v2/summary.json`
  - Result: `C1 run 1: applied flow=2584228a-353b-4f1d-8e9a-033adc978922`
- Targeted C1 repeat after the fix:
  - `/tmp/material-efficiency-live-eval/20260505-233938-t013-c1-repeat-runtime-field-absence/summary.json`
  - Result: C1 applied `3/3`; flows `64bb97d8-a375-4773-991d-cdd12b51c816`, `a8f81fe2-2eef-4c6b-846c-3d0fb10eb6b1`, `03751b3e-b14a-4eb7-ad06-5aa4bc722ff9`.
  - Manual artifact inspection: all three run contracts had `form_fields: []`; all three graphs had `all_previous_steps_count=0`; generated plans used explicit input bindings.
- One broader one-pass create suite still found a separate C1 validation flake:
  - `/tmp/material-efficiency-live-eval/20260505-233614-t013-create-suite-runtime-field-absence/summary.json`
  - Failure log reported `Invalid step reference 'step_k' in input bindings` even though declared refs included `step_k`. Later C1 repeat applied `3/3`, so this is recorded as a separate validation/reference follow-up rather than evidence that the runtime-field absence fix failed.

## Follow-Up

Next high-ROI slice: investigate the C1 validation flake around `Invalid step reference 'step_k' in input bindings` despite `step_k` being listed as declared. Candidate owners are the draft input-binding reference validator and outline repair/self-correction diagnostics, not runtime metadata inference.
