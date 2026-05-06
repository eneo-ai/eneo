# T033 Worker Receipt: Error Paths Preserve Plan Metrics

## TL;DR

- Implemented the eval-runner slice selected by T032.
- HTTP, connection, and generic outer eval errors now share one finalizer.
- Abnormal exits write `error.txt` and then reuse `attach_material_metrics` so saved `plan.json` or `flow.json` material metrics are not discarded.
- Deterministic tests cover HTTP and connection errors after a plan has been saved.
- Live E1 edit run reproduced HTTP 500 and still emitted automated `plan_envelope` metrics.

## Problem

The live eval runner saved useful plan artifacts before late apply/edit failures, but the `HTTPError`, `URLError`, and generic error branches overwrote metric state with `missing_artifacts`. That made failed-but-diagnostic-rich runs look unmeasurable, hiding material-routing evidence needed for the broader Flow AI Builder goal.

## Change

Changed `docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py` so abnormal run exits call `_finalize_error_result(...)`, which:

- sets the error status,
- writes `error.txt`,
- calls the existing `attach_material_metrics(...)` owner,
- returns the populated `CaseRunResult`.

No score-axis semantics changed. No raw eval material, prompts, API keys, or artifacts were added to the repository.

## Red Evidence

The new tests drive `run_case(...)` through late failures after `plan.json` is available. On HEAD before the production change, the error branches set `metrics_implementation = "missing_artifacts"` and did not call `attach_material_metrics(...)`, so these assertions would fail:

- `test_http_error_after_plan_keeps_plan_envelope_material_metrics`
- `test_connection_error_after_plan_keeps_plan_envelope_material_metrics`
- `test_generic_error_after_plan_keeps_plan_envelope_material_metrics`

## Verification

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_live_eval_runner.py -q -k 'http_error or connection_error or material_metrics'
# 4 passed

uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_live_eval_runner.py -q
# 13 passed

uv run --directory backend pyright ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py
# 0 errors, 0 warnings, 0 informations

uv run --directory backend ruff check ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py
# All checks passed

uv run --directory backend ruff format --check ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py
# 2 files already formatted
```

## Live Eval

```bash
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py \
  --api-base http://localhost:8123 \
  --api-key '<local-key>' \
  --include-supplemental \
  --case E1 \
  --runs 1 \
  --edit-flow-id fdd4abc5-35ca-41ed-bca3-10be5102dbc4 \
  --apply \
  --output-dir /tmp/material-efficiency-live-eval/20260506-060512-t033-e1-error-plan-metrics
```

Result:

- `E1 run 1: http_error`
- Summary: `/tmp/material-efficiency-live-eval/20260506-060512-t033-e1-error-plan-metrics/summary.json`
- Error id from local API response: `89a2ccdd`
- `metrics_implementation: automated`
- Step metrics source: `plan_envelope`
- The saved result contains plan-level binding/fan-in/source-duplication metrics despite the HTTP 500.

## Out Of Scope

- This does not diagnose or fix the E1 HTTP 500 root cause.
- This does not change backend Flow AI Builder behavior.
- This does not change score thresholds or material metric definitions.
- This does not address the unrelated dirty Flow AI Builder policy files that still need ownership before the next compiler/planner slice.

## Reviewability

The production change is intentionally small and keeps material-metric derivation in the existing `attach_material_metrics(...)` owner. The new finalizer removes duplicated error-branch assignments and makes future error statuses less likely to drop diagnostics.

Confidence: high.
