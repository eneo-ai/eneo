# T007 Live Eval Rerun Receipt

## Summary

Repaired the live eval runner so it exercises the AI Builder requirements-confirmation lifecycle instead of stopping after the first `requirements_summary` SSE event. Re-ran smoke, create, and supplemental probes against the localhost API.

Raw outputs are intentionally outside git:

- Smoke: `/tmp/material-efficiency-live-eval/20260505-212649-final-smoke/summary.json`
- Create suite: `/tmp/material-efficiency-live-eval/20260505-212703-final-create/summary.json`
- Supplemental probes: `/tmp/material-efficiency-live-eval/20260505-213416-final-supplemental/summary.json`

## Runner Fix

- Parses AI Builder SSE events into `*-events.json` files.
- Records `requirements_version`, checkpoint event names, and builder errors in `summary.json`.
- Sends the required confirmation payload when the builder emits `requirements_summary`:
  - `question_answer.requirements_confirmed=true`
  - `question_answer.requirements_version=<requirements_version>`
- Classifies:
  - `clarification_required` when either planner round emits a `question` event and no plan exists.
  - `builder_error` when the builder emits an SSE `error` event and no plan exists.
  - `no_plan_after_requirements_confirmation` when requirements were confirmed but no plan or error/question was emitted.
- Persists redacted invocation details in `summary.json` so `--runs`, `--apply`, `--publish`, and selected cases are auditable without shell history.

## Live Results

Smoke passed:

- AI Builder sessions endpoint readable: 20 sessions returned.
- Flow list endpoint reachable for all five eval spaces.

Create suite, 3 runs each:

| Case | Result |
|---|---|
| V1 | `clarification_required` 3/3 |
| V2 | `applied` 3/3 |
| V3 | `clarification_required` 3/3 |
| V4 | `clarification_required` 3/3 |
| V5 | `clarification_required` 3/3 |
| C1 | `builder_error` 3/3 |
| C2 | `applied` 3/3 |
| C3 | `applied` 3/3 |
| C4 | `clarification_required` 3/3 |
| C5 | `clarification_required` 3/3 |

C1 failures:

- Runs 1-2: `self_correction_invalid_plan: Plan still invalid after correction.`
- Run 3: `planner_invalid_repair_response: The AI planner failed. Please try again.`

Supplemental probes:

| Case | Result |
|---|---|
| H1 | `clarification_required` 1/1 |
| H2 | `clarification_required` 1/1 |
| N1 | `applied` 1/1 |
| Q1 | `applied` 1/1 |

## Manual Quality Observations

These are manual observations from persisted `flow.json` artifacts, not automated scores.

- V2 generated a grounded audio-to-DOCX flow. Later preparation steps explicitly reference `{{ step_1.output.text }}` and structured section outputs before DOCX creation.
- C2 applied, but still has material-efficiency problems:
  - Step 7 uses `input_source="all_previous_steps"` for PDF preparation.
  - Form fields are only bound in the terminal PDF step as `organization_name`, `report_period`, and `focus_area`.
  - The requested behavior says `focusområde` should steer risk analysis before the final report; the generated risk step does not receive an explicit form-field binding.
- C3 applied, but source/material routing remains weak for the requested multi-document comparison:
  - The flow is a linear previous-step chain.
  - The contradiction step does not receive explicit access to multiple source-specific extracts.
  - The final report is not explicitly bound to selected facts plus comparison output.
- N1 applied but overbuilt a simple translation control into a four-step JSON/text workflow. This is a context-efficiency failure despite successful application.
- Q1 applied with the expected draft -> critique -> final revision topology, and the final step explicitly references both critique and the draft source text.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_live_eval_runner.py -q`
  - `4 passed`
- `cd backend && uv run ruff check ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py`
  - passed
- `cd backend && uv run ruff format --check ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py`
  - passed
- `cd backend && uv run pyright ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py`
  - `0 errors, 0 warnings, 0 informations`

## Claude Peer Review

- Iteration 1: `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260505T192214Z.md`
- Claude rejected the first runner-only version because:
  - classification only checked first-round `question` events,
  - invocation metadata was not persisted,
  - SSE parsing/classification helpers were untested,
  - manual architectural observations needed to be labeled as manual.
- Addressed these points before the final eval rerun.
- Iteration 2: `.codex/artifacts/claude-peer-loop-claude-peer-loop-20260505T193822Z.md`
- Claude returned `GREEN_LIGHT: yes` for recording this as the live-eval phase result, with follow-ups around watchdog behavior, baseline summary metadata, and keeping lifecycle status separate from desired-signal scoring.

## Remaining Follow-Ups

- Add automated flow-shape scoring for known material-efficiency smells:
  - terminal `all_previous_steps`,
  - unused content form fields,
  - form fields only appearing in terminal styling/output steps,
  - linear previous-step chains for multi-source comparison tasks.
- Investigate C1 planner invalid-plan failures as a separate builder-planning reliability slice.
- Add scripted clarification answers for V/C cases where the expected eval path requires continuing past a clarification checkpoint.
