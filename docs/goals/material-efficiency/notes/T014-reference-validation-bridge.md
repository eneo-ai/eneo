# T014 Reference Validation Bridge

## Problem

Post-T013 live eval exposed a separate C1 flake: validation reported `Invalid step reference 'step_k' in input bindings` while the same feedback listed `step_k` among declared draft refs. That contradicted itself and sent repair toward the wrong problem. The failure pointed at the draft-to-runtime reference bridge, not runtime field absence.

## Why It Matters

AI Builder drafts use `plan_step_ref` aliases such as `step_k`; production flow validators expect runtime aliases such as `step_11`. If a declared draft alias leaks into runtime validation, the builder can incorrectly treat a known step as unknown. That makes source-material and binding repairs noisy, can block otherwise valid advanced flows, and weakens the model's ability to fix its own plans.

## Canonical Owner

The narrow ownership boundary for this slice is:

- `backend/src/intric/flows/ai_builder/ai_builder_reference_rewriter.py` owns draft `plan_step_ref` to runtime `step_N` translation before flow-service parity checks.
- `backend/src/intric/flows/ai_builder/ai_builder_validation_references.py` owns draft-layer template reference semantics and supported output-path validation.
- `backend/src/intric/flows/ai_builder/ai_builder_plan_store.py` owns validation feedback text and must not add contradictory declared-ref guidance for runtime alias errors.
- `backend/src/intric/flows/ai_builder/ai_builder_service.py` uses the real `SpecValidationResult` for revision envelopes after the plan-store validation type was tightened.

The larger reference-contract cleanup remains out of scope.

## Change

- Rewrote every template expression whose head matches a declared `plan_step_ref`, regardless of tail shape, instead of only rewriting `ref.output.*`.
- Added draft validation for supported step output paths:
  - supported: `output.text`, `output.structured`, `output.structured.<field>`
  - unsupported: bare refs, bare `output`, `text`, and other tails
- Preserved whole-structured-object references such as `{{ step_a.output.structured }}` for JSON steps.
- Stopped adding declared-step-ref repair guidance when a `flow_step_invalid` message merely contains the English phrase `invalid step reference`.
- Tightened plan-envelope validation typing from `Any` to `SpecValidationResult` and replaced the service revision fake with `SpecValidationResult()`.
- Added tests for declared-alias unsupported paths, whole-structured output references, rewrite coverage for non-`output.*` shapes, and non-contradictory feedback for both runtime alias errors and undeclared `step_z`.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_validator.py tests/unittests/flows/ai_builder/test_ai_builder_plan_store.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py -q`
  - `120 passed`
- `uv run --directory backend pytest tests/unittests/flows/ai_builder -q`
  - `1949 passed, 4 skipped, 12 warnings`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_plan_store.py src/intric/flows/ai_builder/ai_builder_reference_rewriter.py src/intric/flows/ai_builder/ai_builder_validation_references.py src/intric/flows/ai_builder/ai_builder_service.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_store.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py`
  - `All checks passed!`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_plan_store.py src/intric/flows/ai_builder/ai_builder_reference_rewriter.py src/intric/flows/ai_builder/ai_builder_validation_references.py src/intric/flows/ai_builder/ai_builder_service.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_store.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py`
  - `7 files already formatted`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_plan_store.py src/intric/flows/ai_builder/ai_builder_reference_rewriter.py src/intric/flows/ai_builder/ai_builder_validation_references.py src/intric/flows/ai_builder/ai_builder_service.py tests/unittests/flows/ai_builder/test_ai_builder_edit_compiler.py tests/unittests/flows/ai_builder/test_ai_builder_plan_store.py tests/unittests/flows/ai_builder/test_ai_builder_validator.py`
  - `0 errors, 0 warnings, 0 informations`

## Live Evaluation

- Targeted C1 repeat:
  - `/tmp/material-efficiency-live-eval/20260506-000408-t014-c1-reference-bridge/summary.json`
  - C1 applied `3/3`
  - Applied graphs had no exact authoring refs such as `step_a`, no `all_previous_steps`, and `form_fields: []`.
- Final full create suite against the current working tree:
  - `/tmp/material-efficiency-live-eval/20260506-001537-t014-create-suite-reference-bridge-final/summary.json`
  - C1, C2, C3, and V2 applied `1/1`
  - V1, V3, V4, V5, C4, and C5 returned `clarification_required` `1/1`
  - `builder_errors=0`
  - Applied graphs for C1, C2, C3, and V2 had no exact authoring refs such as `step_a` and no `all_previous_steps`.

## Peer Review

Claude peer loop:

- Iteration 1: `GREEN_LIGHT: no`, identified the rewriter/runtime-validator bridge as the likely canonical issue and required red tests.
- Iteration 2: `GREEN_LIGHT: no`, accepted the implementation shape but required two sharper tests.
- Iteration 3: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

Artifact:

- `.codex/artifacts/claude-peer-loop-t014-reference-validation-plan-review-20260505T215921Z.md`
- `.codex/artifacts/claude-peer-loop-t014-reference-validation-implementation-review-20260505T221324Z.md`
- `.codex/artifacts/claude-peer-loop-t014-reference-validation-verification-20260505T221426Z.md`

## Follow-Up

- Collapse the duplicate template-expression regex in the rewriter with the shared variable resolver.
- Replace runtime `BadRequestException(str)` parsing and `_infer_step_ref_from_message` with structured runtime validation errors.
- Continue restraint/topology work for N1 and unnecessary clarification work for Q1/C5.
