# T040 Worker: JSON Terminal Helper Normalization

## Result

Implemented and verified the terminal helper-tail normalization slice for strict JSON terminal contracts.

## Problem

Live C3 failures exposed a broader terminal-contract drift class: a model can create the requested JSON-producing helper as the penultimate step, then leave a pass-through text "final result" step as the terminal step. Strict compiled-spec preparation correctly rejects that shape because the runtime returns the last step.

## Canonical Owner

`backend/src/intric/flows/ai_builder/ai_builder_step_transition_policy.py` remains the canonical owner. It already folds PDF/DOCX helper-before-text tails before compiled-spec validation, so extending the same normalizer to strict JSON terminal helpers avoids a parallel repair path.

## Change

- Extended terminal helper-tail folding to strict terminal output types: JSON, PDF, and DOCX.
- Kept folding limited to adjacent pass-through text tails that read `previous_step`.
- Preserved broad `all_previous_steps` tails as invalid instead of normalizing them away. This keeps material-efficiency problems visible to validation and live eval instead of hiding broad final fan-in.
- Added deterministic coverage in step-transition normalization and compiled-spec preparation tests.

## Verification

- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_compiled_spec_preparation.py -q` -> `40 passed`.
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q` -> `2071 passed, 4 skipped`.
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_compiled_spec_preparation.py` -> `0 errors, 0 warnings, 0 informations`.
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_compiled_spec_preparation.py` -> `All checks passed`.
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_step_transition_policy.py tests/unittests/flows/ai_builder/test_ai_builder_compiled_spec_preparation.py` -> `3 files already formatted`.

## Live Eval

- `/tmp/material-efficiency-live-eval/20260506-084044-t040-c3-json-terminal-normalization-post-allprev-guard/summary.json`
- C3 run 1 applied: `55d90f06-7966-47c1-adcb-f101c285a6c6`.
- C3 run 2 applied: `6018f750-56dd-459d-859b-e2fcd1d47d8e`.
- C3 run 3 hit a transport-level `Remote end closed connection without response` after plan generation artifacts were written.
- The applied C3 flows still have `all_previous_steps_count=1` on the final text step. That is not solved by this slice because T039 terminal-output inference now correctly classifies C3 as a text terminal flow, making JSON-tail normalization irrelevant for C3's broad final fan-in.

## Residual Follow-Ups

- Fix C3 final-step `all_previous_steps` fan-in with a targeted material-routing slice.
- Investigate C3 `no_plan_after_requirements_confirmation` / remote-close flake separately from terminal contract normalization.
- Consider moving final-prose markers into the role-scoped segmenter if more language-specific terminal-output phrases accumulate.
