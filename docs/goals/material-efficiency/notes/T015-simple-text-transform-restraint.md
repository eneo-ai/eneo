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
- Let short-answer and final-version prompts resolve to text terminal output, so
  explicit Q1-style quality chains do not reopen the final-output-mode question.
- Filtered default confirmed-requirements boilerplate before prompt assembly and
  planner signal detection so generic "needs review" text does not masquerade as
  a quality-chain request.
- Replaced duplicate emitted/detected boilerplate strings with shared constants
  in `ai_builder_requirements_state.py`; `ai_builder_server_actions.py` now emits
  those constants.
- Tightened direct-transform matching with boundary-aware markers and
  document-class guards. False positives such as `beskriv om`,
  `skriver om upplevelsen`, `förrätta`, `översätt fakturor`, and
  `sammanfatta leverantörsavtalet` are test-covered.

## Verification

- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_requirements_state.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py -q`
  - `247 passed`
- `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q`
  - `1976 passed, 4 skipped`
- `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_create_feedback.py src/intric/flows/ai_builder/ai_builder_critic_invariants.py src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/ai_builder_plan_proposal_task.py src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py src/intric/flows/ai_builder/ai_builder_requirements_state.py src/intric/flows/ai_builder/ai_builder_server_actions.py tests/unittests/flows/ai_builder/test_ai_builder_create_feedback.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_ai_builder_plan_proposal_task.py tests/unittests/flows/ai_builder/test_ai_builder_plan_quality_critic.py tests/unittests/flows/ai_builder/test_ai_builder_requirements_state.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_discovery_flow.py`
  - `0 errors, 0 warnings, 0 informations`
- `uv run --directory backend ruff check ...`
  - `All checks passed!`
- `uv run --directory backend ruff format --check ...`
  - `14 files already formatted`
- `python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --include-supplemental --case N1 --case Q1 --case C5 --runs 3 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260506-011206-t015-boundary-marker-targeted`
  - `N1` applied `3/3`; every generated flow had exactly one text step.
  - `Q1` applied `3/3`; two runs preserved the exact draft -> critique -> final chain, and one run added a redundant final formatting pair.
  - `C5` stayed `clarification_required` `3/3`.
- `python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --case V2 --case C2 --case C3 --runs 2 --apply --publish --output-dir /tmp/material-efficiency-live-eval/20260506-005642-t015-v2-c2-c3-recheck`
  - `V2`, `C2`, and `C3` applied `2/2` after a broader one-pass suite showed live variance.
- Manual runtime check:
  - Flow `764dcc54-e8fd-4381-a646-b14182777cbd`
  - Run `e0272777-9b25-43ad-aa0e-c35660a8e508`
  - Completed in one model step with 46 input tokens and 10 output tokens.
  - Output: `See you at the meeting tomorrow.`

## Peer Review

- Iteration 1: `.codex/artifacts/claude-peer-loop-t015-simple-text-transform-restraint-review-20260505T225417Z.md`
  - `GREEN_LIGHT: no`, `MIN_SCORE: 7`
  - Valid blocker: duplicate boilerplate strings between emitter and detector.
- Iteration 2: `.codex/artifacts/claude-peer-loop-t015-direct-text-transform-restraint-implementation-review-20260505T230851Z.md`
  - `GREEN_LIGHT: no`, `MIN_SCORE: 6`
  - Valid blocker: raw substring matching made `skriv om` match phrases like
    `beskriv om`.
- Iteration 3: `.codex/artifacts/claude-peer-loop-t015-direct-text-transform-restraint-verification-after-boundary-fix-20260505T231926Z.md`
  - `GREEN_LIGHT: yes`, `MIN_SCORE: 7`
  - Claude accepted the boundary-aware direct-transform matching, document-class
    guards, tightened terminal text-output markers, and false-positive regression
    tests as sufficient for this slice.

## Remaining Follow-Up

- C5 still over-clarifies material source even when the prompt explicitly says the
  user records or uploads audio.
- C2/C3 remain live-variable; direct recheck applied, but topology quality still
  varies.
- Q1 still has topology variance: one live run added a redundant final formatting
  pair after the explicit draft -> critique -> final chain.
