# T021 Live Eval Material Metrics

## TL;DR

T021 promotes material-efficiency metric computation into one typed backend-owned helper and wires the live eval runner to use it.
Applied/planned live eval results now emit automated numeric metrics instead of `manual_review_required`.
The helper reuses the canonical template reference analyzer rather than adding runner-local parsing.
Focused unit, full AI Builder unit, pyright, ruff, and live eval checks passed for this slice.
The earlier full-suite caveat is resolved by the follow-up targeted-underlag composer input-type fix; the local AI Builder suite is now green.

## Problem

The goal requires measurable material efficiency, but post-T019 live eval summaries still reported manual-only metrics. That made it impossible to compare binding bytes, fan-in, structured reference use, source duplication, or `all_previous_steps` usage across live runs without hand inspection.

## Canonical Owner

Metric computation now lives in `backend/src/intric/flows/ai_builder/ai_builder_material_metrics.py`.

This is the canonical owner because it is pure AI Builder diagnostic logic and can be reused by both backend unit tests and the external live eval runner. The runner remains responsible only for loading saved artifacts and projecting them into the helper's typed input shape.

## Change

- Added `MaterialMetricStep` and `MaterialMetrics` as typed diagnostic contracts.
- Added `material_metric_steps_from_draft`, `compute_material_metrics`, and `compute_step_material_metrics`.
- Replaced test-local metric parsing in `test_ai_builder_step_transition_policy.py` with the shared helper.
- Updated the live eval runner to compute metrics from saved `flow.json` first, then `plan.json` when no flow is available.
- Updated live eval summary metadata from manual metric review to automated plan/flow artifact metrics.
- Added runner tests for applied-flow, plan-only, edit-flow, missing-artifact, malformed-artifact, and score-axis behavior.
- Updated the goal runner examples to use the backend `uv` invocation required by shared backend imports.

## Verification

Focused tests:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_live_eval_runner.py -q
```

Result: `44 passed in 4.87s`.

Strict typing:

```bash
uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_live_eval_runner.py ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py
```

Result: `0 errors, 0 warnings, 0 informations`.

Lint and format:

```bash
uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_live_eval_runner.py ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py
uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_live_eval_runner.py ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py
```

Result: all checks passed; files already formatted.

Live eval:

```bash
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --include-supplemental --runs 1 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260506-030534-t021-live-eval-material-metrics
```

Result summary:

| Case | Status | Metrics implementation | Metrics |
|---|---|---|---|
| C1 | applied | automated | binding_bytes=1814, fan_in_width=12, structured_field_count=13, whole_output_reference_count=22, source_duplication_count=11, all_previous_steps_count=0 |
| C2 | applied | automated | binding_bytes=1782, fan_in_width=7, structured_field_count=14, whole_output_reference_count=7, source_duplication_count=0, all_previous_steps_count=0 |
| C3 | applied | automated | binding_bytes=21, fan_in_width=0, structured_field_count=0, whole_output_reference_count=0, source_duplication_count=0, all_previous_steps_count=0 |
| C5 | applied | automated | binding_bytes=1010, fan_in_width=7, structured_field_count=5, whole_output_reference_count=12, source_duplication_count=5, all_previous_steps_count=0 |
| N1 | applied | automated | binding_bytes=17, fan_in_width=0, structured_field_count=0, whole_output_reference_count=0, source_duplication_count=0, all_previous_steps_count=0 |
| Q1 | applied | automated | binding_bytes=88, fan_in_width=2, structured_field_count=0, whole_output_reference_count=2, source_duplication_count=0, all_previous_steps_count=0 |

Overall live status counts: 6 applied, 7 clarification_required, 1 no_plan, 2 skipped.

Post-review refactor live eval:

```bash
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --include-supplemental --case N1 --case Q1 --case C5 --runs 1 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260506-032301-t021-post-review-refactor-metrics
```

Result summary:

| Case | Status | Metrics implementation | Metrics |
|---|---|---|---|
| C5 | applied | automated | binding_bytes=990, fan_in_width=7, structured_field_count=5, whole_output_reference_count=11, source_duplication_count=5, all_previous_steps_count=0 |
| N1 | applied | automated | binding_bytes=17, fan_in_width=0, structured_field_count=0, whole_output_reference_count=0, source_duplication_count=0, all_previous_steps_count=0 |
| Q1 | applied | automated | binding_bytes=88, fan_in_width=2, structured_field_count=0, whole_output_reference_count=2, source_duplication_count=0, all_previous_steps_count=0 |

Final targeted live check:

```bash
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --include-supplemental --case N1 --case Q1 --case C5 --runs 1 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260506-t021-final-live-metrics
```

Result summary:

| Case | Status | Metrics implementation | Metrics |
|---|---|---|---|
| C5 | applied | automated | binding_bytes=1180, fan_in_width=4, structured_field_count=8, whole_output_reference_count=5, source_duplication_count=2, all_previous_steps_count=0 |
| N1 | applied | automated | binding_bytes=17, fan_in_width=0, structured_field_count=0, whole_output_reference_count=0, source_duplication_count=0, all_previous_steps_count=0 |
| Q1 | no_plan_after_requirements_confirmation | not_applicable | no saved plan/flow artifact to score |

## Full Suite

The full local AI Builder unit suite was run with the required `-n 4` after the targeted-underlag composer input-type fix:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q
```

Result: `2014 passed, 4 skipped`.

## Acceptance

- Applied/planned live eval results no longer require manual review for numeric material metrics.
- Metric computation has one typed canonical owner.
- Runner artifact loading does not duplicate template-reference parsing.
- Focused behavior tests cover plan and flow artifacts.
- The earlier compiler/dataflow expectation drift is resolved by the separate T022 test alignment, and the local AI Builder unit suite is green.

## Risk

Source duplication currently counts `output.text` references to source-surfacing flow-input text steps. This is intentionally conservative and avoids counting ordinary text-output draft steps as source duplication. Future metric refinements should extend the shared helper rather than adding runner-local counters.

Confidence: high.
