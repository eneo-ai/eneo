# T026 Live Eval Step Hotspots

## TL;DR

T026 adds privacy-safe per-step material metric rows to the shared metric helper and live eval summaries.
The rows contain only numeric metrics, step order, and metric source; they do not include prompt text, source text, binding bodies, previews, or API payloads.
Focused tests, full AI Builder tests, pyright, ruff check, and format checks passed.
Live eval applied and published C1, C5, N1, and Q1 in one combined summary.
The strongest follow-up signal is now concrete: C1 step 12 and C5 step 8 are the largest binding/fan-in hotspots.

## Problem

Aggregate metrics showed that C1/C5 had high binding bytes, fan-in, and source duplication, but the summary did not identify which generated step caused the cost. Without per-step rows, the next behavior slice would still require manual flow inspection and could optimize the wrong boundary.

## Canonical Owner

Per-step metric computation extends `backend/src/intric/flows/ai_builder/ai_builder_material_metrics.py`.

The live eval runner projects saved plan/flow artifacts into `MaterialMetricStep` and serializes numeric rows, but it does not parse templates or compute metric semantics itself.

## Change

- Added `compute_per_step_material_metrics`.
- Added `StepMetricsRow` to the live eval runner summary shape.
- Emitted `step_metrics` for saved `flow.json` and `plan.json` artifacts.
- Kept missing/malformed artifacts as empty `step_metrics`.
- Preserved step metrics in redacted baseline summaries because the rows contain no raw material.
- Made per-step `all_previous_steps_count` local to the selected step, so hotspot rows do not smear one broad-input step across every row.

## Verification

Focused tests:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_live_eval_runner.py -q
```

Result: `19 passed`.

Full AI Builder tests:

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q
```

Result: `2016 passed, 4 skipped`.

Strict typing:

```bash
uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_live_eval_runner.py ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py
```

Result: `0 errors, 0 warnings, 0 informations`.

Lint and format:

```bash
uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_live_eval_runner.py ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py
uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_ai_builder_material_metrics.py tests/unittests/flows/ai_builder/test_live_eval_runner.py ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py
```

Result: ruff check passed; format check passed.

Claude commit-gate:

- Artifact: `.codex/artifacts/claude-peer-loop-t026-implementation-review-20260506T020833Z.md`
- Verdict: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`
- Codex verified Claude's staging warning locally and will stage only T026 files.

## Live Eval

Combined summary:

`/tmp/material-efficiency-live-eval/20260506-035321-t026-step-hotspots/summary.json`

Command:

```bash
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --include-supplemental --case C1 --case C5 --case N1 --case Q1 --runs 1 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260506-035321-t026-step-hotspots
```

| Case | Status | Flow | Rows | Binding bytes | Fan-in | Structured fields | Whole output refs | Source duplication | Step source sum | all_previous |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C1 | applied | `542443ad-fdbf-48d5-9038-564d350cd9e8` | 13 | 1378 | 11 | 10 | 20 | 10 | 10 | 0 |
| C5 | applied | `23db314d-4454-4dda-b491-8e6e96328d10` | 9 | 1146 | 7 | 5 | 12 | 5 | 5 | 0 |
| N1 | applied | `bf4b17ac-dcd6-4a06-bb98-83c8d8819f52` | 1 | 17 | 0 | 0 | 0 | 0 | 0 | 0 |
| Q1 | applied | `2aa7fa49-19c3-45ff-86b4-0cc60bcb3ffe` | 3 | 88 | 2 | 0 | 2 | 0 | 0 | 0 |

Highest C1 rows:

| Step | Binding bytes | Fan-in | Structured fields | Whole output refs | Source duplication |
|---:|---:|---:|---:|---:|---:|
| 12 | 717 | 11 | 10 | 2 | 1 |
| 11 | 72 | 2 | 0 | 2 | 1 |
| 3 | 71 | 2 | 0 | 2 | 1 |

Highest C5 rows:

| Step | Binding bytes | Fan-in | Structured fields | Whole output refs | Source duplication |
|---:|---:|---:|---:|---:|---:|
| 8 | 705 | 7 | 5 | 3 | 1 |
| 6 | 153 | 2 | 0 | 2 | 1 |
| 3 | 71 | 2 | 0 | 2 | 1 |

All rows had only these keys:

- `step_order`
- `metrics_source`
- `binding_bytes`
- `fan_in_width`
- `source_duplication_count`
- `whole_output_reference_count`
- `structured_field_count`
- `all_previous_steps_count`

No row contained raw prompt, question, binding body, preview, source text, or user-controlled material.

## Acceptance

- The live eval summary now localizes material hotspots to concrete step orders.
- The rows are privacy-safe numeric diagnostics, not raw material.
- The helper remains the only metric computation owner.
- Live artifacts show the next behavior slice can target specific high-cost boundaries rather than optimizing source preservation globally.

## Follow-Up

Do not remove repeated source references broadly yet. The next behavior Worker should start from the now-visible hotspots:

- C5 step 8: final composer material fan-in and structured field fan-in.
- C1 step 12: final composer with expected fan-in but high binding bytes.
- C1/C5 intermediate extraction steps: repeated source duplication in section-by-section chains.

Confidence: high.
