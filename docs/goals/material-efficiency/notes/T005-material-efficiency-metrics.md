# T005 Worker Receipt: Material-Efficiency Assertions

## Result

Done. Added a deterministic longer-chain material-efficiency assertion to keep the source-material routing slice honest about context cost.

## Scope

Changed only:

- `backend/tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`
- `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`
- `docs/goals/material-efficiency/notes/T005-material-efficiency-metrics.md`

## Added Coverage

`test_normalize_ai_builder_spec_bounds_material_metrics_for_section_chain` builds a five-step section-analysis flow:

- source transcription
- summary JSON
- decisions JSON
- risks JSON
- final text report

For each JSON-after-JSON/report boundary after normalization, the test asserts:

- binding byte size stays under a small deterministic cap
- fan-in width is exactly 2
- no structured subfield fan-out is introduced by the normalizer
- only whole immediate structured output plus one source text reference are present
- source text is referenced once per boundary
- no `all_previous_steps` fallback appears

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py -q -k material_metrics`
  - `1 passed, 26 deselected`
- `uv run --directory backend ruff check tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`
  - `All checks passed`
- `uv run --directory backend ruff format --check tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`
  - `1 file already formatted`
- `uv run --directory backend pyright tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py`
  - `0 errors, 0 warnings, 0 informations`

## Peer Review

[no-peer-review] This was a narrow test-only follow-up that added deterministic assertions around behavior already reviewed and green-lit in T004. No production code or architecture boundary changed.
