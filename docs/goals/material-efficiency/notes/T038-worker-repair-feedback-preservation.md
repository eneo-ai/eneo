# T038 Worker Receipt: Repair Feedback Preservation

## Result

Done.

## Problem

C2 live evals could fail with `self_correction_invalid_plan` while exposing no
concrete validation or parse feedback to the debug artifacts. The proposal
repair boundary logged forced-tool retry failures, but returned only
`EventBatch | None`, so `request_self_correction` had no typed way to preserve
sanitized feedback when a forced retry still failed.

## Change

- Added `ForcedToolRetryOutcome` in `ai_builder_proposal_repair.py` with
  `events`, `feedback`, and `failure_kind`.
- Changed forced retry internals to return the typed outcome instead of
  collapsing all unsuccessful paths to `None`.
- Preserved JSON-text fallback validation feedback, invalid forced tool-call
  parse feedback, and forced retry validation feedback through the
  self-correction error event.
- Kept the legacy `retry_forced_proposal_after_text` wrapper returning only
  events for callers that do not consume repair feedback.

## Red Evidence

Targeted tests failed before the source changes because forced retry validation
and parse feedback were discarded before the self-correction boundary could emit
it.

## Verification

- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py -q`
  - `65 passed`
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q`
  - `2052 passed, 4 skipped`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  - `0 errors, 0 warnings, 0 informations`
- `uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  - `All checks passed`
- `uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_proposal_repair.py src/intric/flows/ai_builder/ai_builder_proposal_processor.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_repair.py tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py`
  - `4 files already formatted`

## Live Eval

- First C2 rerun:
  `/tmp/material-efficiency-live-eval/20260506-073527-t038-c2-repair-feedback/summary.json`
  - Result: `builder_error`
  - Failure: `invalid_session_transition: cancelled -> awaiting_approval`
  - Interpretation: did not exercise the original forced-retry feedback path.
- Second C2 rerun:
  `/tmp/material-efficiency-live-eval/20260506-073651-t038-c2-repair-feedback-rerun2/summary.json`
  - Result: `applied`
  - Metrics: `binding_bytes=1632`, `fan_in_width=7`,
    `structured_field_count=12`, `whole_output_reference_count=6`,
    `all_previous_steps_count=0`.

## Follow-Up

- The live C2 failure did not reproduce the original `self_correction_invalid_plan`
  path after this change. The feedback-preservation contract is verified
  deterministically, while live C2 remains flaky between session-transition
  failure and successful apply.
- The next slice should investigate `invalid_session_transition:
  cancelled -> awaiting_approval` as a builder session lifecycle issue.
