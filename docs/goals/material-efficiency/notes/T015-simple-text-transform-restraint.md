# T015 Simple Text Transform Restraint

## Result

Done.

## Problem

Live eval case `N1` showed that the AI Builder overbuilt a direct one-sentence
translation request into 4-5 model steps with analysis, review, and sometimes
JSON. A manual runtime run of one pre-fix N1 flow completed but spent four model
steps and 504 output tokens to produce one translated sentence.

## Canonical Owners

- Direct planner pattern signals: `backend/src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py`
- Create-plan quality contract: `backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py`
- Direct text-terminal output inference: `backend/src/intric/flows/ai_builder/ai_builder_framework_policy.py`
- User-facing create repair guidance: `backend/src/intric/flows/ai_builder/ai_builder_create_feedback.py`
- Confirmed-requirements boilerplate ownership/filtering: `backend/src/intric/flows/ai_builder/ai_builder_requirements_state.py`
- Deterministic requirements-summary emission: `backend/src/intric/flows/ai_builder/ai_builder_server_actions.py`

## Change

- Added `PlannerPatternSignals.is_simple_text_transform` for direct text-to-text
  requests such as translation, correction, rewriting, shortening, or summarizing
  a supplied snippet.
- Added the `simple_text_transform_must_remain_single_step` critic invariant.
  Direct text transforms without files, form fields, JSON, or explicit review
  now reject unrequested JSON/review/artifact/multi-step plans.
- Taught the plan proposal system prompt that direct text transformations default
  to one text step unless the user explicitly asks for JSON, review, form fields,
  artifacts, or extra steps.
- Let text-answer and final-version prompts resolve to text terminal output, so a
  plain Q1-style quality chain does not reopen the final-output-mode question.
- Filtered default confirmed-requirements boilerplate before prompt assembly and
  planner signal detection so generic "needs review" text does not masquerade as
  a quality-chain request.
- Replaced duplicate emitted/detected boilerplate strings with shared constants
  in `ai_builder_requirements_state.py`; `ai_builder_server_actions.py` now emits
  those constants.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_requirements_state.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py -q`
  - `241 passed, 1 warning`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_create_feedback.py src/intric/flows/ai_builder/ai_builder_critic_invariants.py src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py src/intric/flows/ai_builder/ai_builder_requirements_state.py src/intric/flows/ai_builder/ai_builder_server_actions.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_requirements_state.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_discovery_flow.py`
  - `0 errors, 0 warnings, 0 informations`
- `uv run --directory backend ruff check ...`
  - `All checks passed!`
- `uv run --directory backend ruff format --check ...`
  - `11 files already formatted`
- `python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --include-supplemental --case N1 --case Q1 --runs 3 --apply --output-dir /tmp/material-efficiency-live-eval/20260506-004653-t015-simple-transform-restraint`
  - `N1` applied `3/3`; all generated flows had exactly one text step.
  - `Q1` was `clarification_required` once and applied `2/3`; applied flows preserved the explicit draft -> critique -> final quality chain.
- Manual runtime check:
  - Flow `764dcc54-e8fd-4381-a646-b14182777cbd`
  - Run `e0272777-9b25-43ad-aa0e-c35660a8e508`
  - Completed in one model step with 46 input tokens and 10 output tokens.
  - Output: `See you at the meeting tomorrow.`

## Peer Review

- Iteration 1: `.codex/artifacts/claude-peer-loop-t015-simple-text-transform-restraint-review-20260505T225417Z.md`
  - `GREEN_LIGHT: no`, `MIN_SCORE: 7`
  - Valid blocker: duplicate boilerplate strings between emitter and detector.
- Iteration 2: `.codex/artifacts/claude-peer-loop-t015-simple-text-transform-restraint-verification-20260505T225943Z.md`
  - `GREEN_LIGHT: yes`, `MIN_SCORE: 8`

## Remaining Follow-Up

- C5 still over-clarifies material source even when the prompt explicitly says the
  user records or uploads audio.
- C2/C3 remain flaky in live eval.
- Q1 still has one clarification run in the targeted live eval and a prior runtime
  run hung on its final step; that is a separate runtime/planner stability issue.
- Optional hardening: add Swedish quality-chain and edit-path critic tests, and
  narrow broad text-terminal marker phrases.
