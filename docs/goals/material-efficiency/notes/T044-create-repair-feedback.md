TL;DR
- C2 and C5 post-T043 failures were traced to lossy create-mode repair guidance.
- C2 now preserves `duplicate_step_name` as a structured failure code and adds outline-specific uniqueness guidance on the next repair prompt.
- C5 create-mode critic feedback now names the actual outline fields: `output_type="json"` and `output_fields`.
- Unit and processor-level tests cover the failure-code path and create-mode feedback translation.
- Live C2/C5 smoke passed against `http://localhost:8123`; the broader one-run create suite had no builder errors.

## Problem

Post-T043 live eval had two remaining flaky create-mode failures:

- C2 run 3: `self_correction_invalid_plan` after duplicate semantic step name.
- C5 run 2: `self_correction_quality_failure` after missing structured extraction guidance.

The common issue was not validation itself. The repair loop was asking the model to correct the plan without preserving enough structured failure context or naming the create-mode fields the model can actually emit.

## Canonical Owners

| Concept | Owner |
|---|---|
| Hard duplicate-name validity | `backend/src/intric/flows/ai_builder/ai_builder_validator.py` |
| Tool failure to self-correction prompt | `backend/src/intric/flows/ai_builder/ai_builder_proposal_repair.py` |
| Create-mode critic remediation translation | `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py` |
| Outline-facing structured fields | `backend/src/intric/flows/ai_builder/ai_builder_create_outline.py` |

## Changes

- Added `failure_codes` to `ToolProcessingResult`.
- Threaded validation error codes from create/compiled validation failures.
- Added duplicate-step-name guidance keyed by `duplicate_step_name`, not by parsing feedback text.
- Updated create-mode structured extraction remediations to mention `output_type="json"` and `output_fields`.
- Kept compiled/edit-mode critic remediation language on `output_contract`.

## Deferred Debt

The current `CREATE_CRITIC_REMEDIATION` table is still a hand-maintained translation layer from compiled critic concepts to outline-facing create-mode guidance. That is acceptable for this slice because the table is already the canonical owner and has coverage. If the semantic invariant table grows or another mismatch appears, fold outline-facing remediation into the invariant model itself, for example as `remediation_outline`, instead of growing a parallel translation table indefinitely.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py -q`
  - `83 passed, 1 warning`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_proposal_processor.py src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  - `0 errors, 0 warnings, 0 informations`
- `ruff check ...`
  - `All checks passed`
- `ruff format --check ...`
  - `6 files already formatted`
- Targeted live smoke:
  - `run_flow_ai_builder_live_eval.py --api-base http://localhost:8123 --case C2 --case C5 --runs 1 --apply`
  - Summary: `/tmp/material-efficiency-live-eval/20260506-t044-c2-c5-live-8123-base/summary.json`
  - Result: C2 `applied`, C5 `applied`
- Broader live regression:
  - `run_flow_ai_builder_live_eval.py --api-base http://localhost:8123 --all --runs 1 --apply`
  - Summary: `/tmp/material-efficiency-live-eval/20260506-t044-create-suite-live-8123/summary.json`
  - Result: C1/C2/C3/C5/V2 `applied`; V1/V3/V4/V5/C4 `clarification_required`; no `builder_errors`

## Claude

- Plan gate artifact: `.codex/artifacts/claude-peer-loop-t044-create-mode-repair-feedback-plan-20260506T133543Z.md`
- Verdict: changes required before implementation.
- Addressed blockers by using structured failure codes, adding processor-level coverage, isolating create-mode output-field guidance, and documenting the deferred invariant-remediation debt. Commit-gate pass returned green after implementation review.
