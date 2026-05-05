TL;DR
- Fixed an edit-mode false-positive diff exposed by the full AI Builder suite.
- Existing-flow baselines now use the same full-spec normalization scope as compiled edit previews.
- Added a direct source-material regression so normalization-only prompt completion stays invisible in user-facing diffs.
- Re-ran smoke and create live evals through the Python runner; C2 routing improved, C1 still fails on a separate quality-gate issue.
- Claude peer review green-lit the patch after one revision.

# T012 - Edit Diff Baseline Normalization

## Problem

After T011, the full AI Builder unit suite exposed an edit-diff false positive. An output-only edit to the terminal step reported an intermediate source-material step as `modified` because compiled edit previews were normalized as a full `FlowDraftSpecCore`, while existing-flow diff baselines were only normalized one step at a time.

That made topology-only normalization, such as source-material underlag completion, appear as a user-requested change.

## Change

`_build_step_changes` now:

- converts existing `FlowStep` values to `StepSpec` with the same plan refs as compiled edit steps when available,
- rewrites existing runtime aliases,
- runs `normalize_ai_builder_spec` once over the whole baseline spec,
- compares normalized baseline steps against normalized compiled steps by `existing_step_ref`.

The stale golden coverage matrix row was also updated to the renamed form-field lifecycle test.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py::TestTransitionNormalization -q`
  - `3 passed`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py -q`
  - `47 passed`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder -q`
  - `1933 passed, 4 skipped`
- `cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py`
  - `All checks passed!`
- `cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py`
  - `3 files already formatted`
- `cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_golden_coverage_matrix.py`
  - `0 errors, 0 warnings, 0 informations`

## Claude Review

Claude peer loop session: `t012-edit-diff-baseline-normalization`

- Iteration 1: `GREEN_LIGHT: no`, `MIN_SCORE: 6`; required one normalization gate, dead-code removal, and a source-material-specific regression test.
- Iteration 2: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Artifacts:

- `.codex/artifacts/claude-peer-loop-t012-edit-diff-baseline-normalization-20260505T211822Z.md`
- `.codex/artifacts/claude-peer-loop-t012-edit-diff-baseline-normalization-iteration-2-20260505T212157Z.md`

## Live Eval Evidence

Raw outputs remain outside git under `/tmp/material-efficiency-live-eval`.

- Smoke rerun: `/tmp/material-efficiency-live-eval/20260505-230733-t011-smoke-rerun/summary.json`
  - API smoke succeeded.
- Targeted C2 rerun: `/tmp/material-efficiency-live-eval/20260505-230801-t011-c2-rerun/summary.json`
  - `C2`: `applied`
  - Applied flow: `2837f8d7-644c-42f4-890e-4a98a0a275c3`
  - Observed body composer no longer used `all_previous_steps`; it used explicit JSON/form-field references.
  - Remaining quality debt: the generated flow still started with document-to-JSON, so full source preservation is partial through extracted `source_facts`/`uncertainties`.
- One-run create suite rerun: `/tmp/material-efficiency-live-eval/20260505-230918-t011-create-suite-rerun/summary.json`
  - `V2`, `C2`, and `C3`: `applied`
  - `V1`, `V3`, `V4`, `V5`, `C4`, `C5`: `clarification_required`
  - `C1`: `builder_error`

## Remaining Follow-Ups

- C1 is now the highest-ROI next defect: live logs show the quality repair loop demands named input fields even when the case explicitly says no inmatningsfält are needed.
- C2 routing improved for the broad-context issue, but source preservation is still weaker than desired when the builder chooses document-to-JSON before a text underlag.
- V1 may be asking a noisy final-output clarification for a simple text-summary request.
