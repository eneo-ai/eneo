# T007 Live Eval Receipt

## Result

Live smoke succeeded, but create-case eval did not produce plans. Treat this as an eval runner/API contract blocker, not as evidence that generated flow quality regressed or improved.

## Commands

Smoke:

```bash
python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke
```

Result:

- Summary: `/tmp/material-efficiency-live-eval/20260505-205343/summary.json`
- AI Builder sessions readable: 20 sessions
- Flow list endpoint reachable for all five eval spaces
- All five eval spaces returned 0 listed flows

Create suite:

```bash
python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --runs 3 --apply
```

Result:

- Summary: `/tmp/material-efficiency-live-eval/20260505-205402/summary.json`
- V1-V5 and C1-C5 each ran 3 times across the five spaces
- All 30 runs reported `no_plan`
- No flows were applied
- No run-contract, publish, run, step-output, or evidence endpoints could be exercised because no plan/flow IDs were produced

## Manual Inspection

For simple vague cases such as V1, the builder returned a clarification question, for example asking what final output mode the flow should produce. That is expected for underspecified prompts.

For advanced cases such as C1 and C2, the SSE stream included `architecture_committed` and a requirements summary, but the session later had:

- `latest_plan_id: null`
- `GET /api/v1/flows/ai-builder/sessions/{session_id}/plans` returned an empty `plans` list
- session status was `cancelled`

Example inspected raw path:

- `/tmp/material-efficiency-live-eval/20260505-205402/C1-run1/message.sse`
- `/tmp/material-efficiency-live-eval/20260505-205402/C1-run1/session.json`

## Interpretation

The API and sessions are reachable, but the current runner cannot obtain plans from the create-case sequence. This may be because:

- the runner does not answer clarification questions
- the runner assumes plans are available immediately after `architecture_committed`
- the AI Builder endpoint contract now requires an additional approval/continuation message after architecture commit
- planner dispatch completed as a requirements summary but did not materialize a draft plan before the session was cancelled

This run should not be scored as a flow-quality failure. It is a live-eval harness/contract failure to investigate before using the live suite as a regression gate.

## Follow-Up

- Update the runner to support structured clarification answers for V cases.
- For advanced cases, inspect the expected post-`architecture_committed` sequence and add polling or continuation if required by the current API contract.
- Add a deterministic runner test with a fake AI Builder session lifecycle so `architecture_committed` without plans is classified separately from actual plan-quality failure.
- Re-run V1-V5 and C1-C5 after the runner can reliably reach plan IDs.

## Raw Output Policy

Raw API material remains under `/tmp/material-efficiency-live-eval/...` and was not copied into the repository.
