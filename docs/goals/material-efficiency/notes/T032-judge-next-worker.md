# T032 Judge Next Worker

## Decision

Activate T033.

## Problem

T031 could not classify the live E1 apply HTTP 500s because backend telemetry/log rows were not accessible locally. A compiler or materializer behavior fix would be guesswork. The next slice should improve long-term evidence quality without changing backend behavior.

## Evidence

- `run_flow_ai_builder_live_eval.py` writes `plan.json` before applying a plan.
- Its `HTTPError`, `URLError`, and generic `Exception` exits hardcode `metrics_implementation = "missing_artifacts"`.
- The existing `attach_material_metrics` helper already owns material metrics derivation and falls back from `flow.json` to `plan.json`.
- Existing tests cover plan-envelope and flow-artifact metric extraction directly.
- Grep for `metrics_implementation` and `"automated"` found only the eval runner and tests; the summary redaction path copies the value and does not treat `automated` as applied-success.

## Claude Review

- Iteration 1: `changes_required`, because the first draft test would have called the helper directly and passed on HEAD, and because only the HTTPError branch was scoped.
- Iteration 2: `green`, min score 9, after revising the worker to drive `run_case`, route all sibling error branches through one finalizer, and pin live-eval summary assertions.

Artifacts:

- `.codex/artifacts/claude-peer-loop-t032-judge-next-worker-after-apply-log-blocker-20260506T035826Z.md`
- `.codex/artifacts/claude-peer-loop-t032-judge-next-worker-after-apply-log-blocker-revision-20260506T040129Z.md`

## Worker Scope

T033 should make every live-eval abnormal run exit attach available material metrics from saved artifacts before returning, so late HTTP/URL/generic errors keep plan-envelope material metrics instead of losing diagnostics.

Allowed files:

- `docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py`
- `backend/tests/unittests/flows/ai_builder/test_live_eval_runner.py`
- `docs/goals/material-efficiency/flow-ai-builder-material-efficiency-state.yaml`
- `docs/goals/material-efficiency/notes/T032-judge-next-worker.md`
- `docs/goals/material-efficiency/notes/T033-live-eval-error-plan-metrics.md`

Verification must use `-n 4` for pytest commands. Live eval must rerun E1 against an existing unpublished C1 flow or a fresh C1 flow and inspect the `summary.json` fields.
