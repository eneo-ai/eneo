# T009 Live Eval Publish Runtime Inspection

## Result

Done.

## Problem

The live eval runner inspected `run-contract` before publishing an applied flow.
That produced false `flow_not_published` artifacts during `--publish` runs even
when the flow was successfully published immediately afterward.

## Change

- Split authoring inspection from published runtime inspection.
- Kept draft/authoring artifacts before publish:
  - `flow.json`
  - `graph.json`
  - `input-policy.json`
  - `template-files.json`
- Moved runtime-only artifacts after publish:
  - `published.json`
  - `run-contract.json`
  - post-publish `input-policy.json`
- Added a regression test that records API call order and asserts
  `POST /publish/` happens before `GET /run-contract/`.

## Verification

- `uv run --directory backend pytest tests/unittests/flows/ai_builder/test_live_eval_runner.py -q`
  - `5 passed`
- `cd backend && uv run ruff check ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py`
  - `All checks passed!`
- `cd backend && uv run ruff format --check ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py`
  - `2 files already formatted`
- `cd backend && uv run pyright ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py tests/unittests/flows/ai_builder/test_live_eval_runner.py`
  - `0 errors, 0 warnings, 0 informations`

## Live Check

Command:

```bash
python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py \
  --case V2 --runs 1 --apply --publish \
  --output-dir /tmp/material-efficiency-live-eval/20260505-220834-post-runner-fix-publish
```

Result:

- V2 applied and published flow `01f3d8b1-3510-4ea3-9e57-f3a0d3fc8df5`.
- `published.json` exists and reports `published_version: 1`.
- `run-contract.json` exists and reports:
  - `flow_id: 01f3d8b1-3510-4ea3-9e57-f3a0d3fc8df5`
  - `published_flow_version: 1`
  - `steps_requiring_input: 1`
  - `form_fields: 0`
- `run-contract.json.error.txt` was not created.

## Peer Review

`[no-peer-review]` This was a narrow eval-runner sequencing fix with a direct
regression test and live smoke proof. It did not change production Flow AI
Builder behavior or architecture.

## Remaining Work

- Fix the underlying C1/C2/C3/N1 planner instability seen in live evals.
- Promote C2 form-field timing into a deterministic production behavior test.
- Investigate real-run step 2 hanging after successful V2 transcription.
