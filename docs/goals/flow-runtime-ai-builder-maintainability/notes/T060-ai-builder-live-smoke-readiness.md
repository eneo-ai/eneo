# T060 AI Builder Live Smoke Readiness

## Verdict

Live AI Builder material-efficiency smoke is blocked by missing local API credentials in the current environment.

## Evidence

| Check | Result |
|---|---|
| Existing runner | `docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py` is the canonical live-eval entry point. |
| Existing cases | Runner defines V1-V5 and C1-C5; state lists five eval spaces in `checks.live_eval.spaces`. |
| API server | `http://localhost:8123/api/v1/flows/ai-builder/sessions` responds with HTTP 401 without a key, so the server is reachable. |
| Host env | `ENEO_LOCAL_API_BASE=missing`, `ENEO_LOCAL_API_KEY=missing`. |
| App container env | `ENEO_LOCAL_API_KEY=missing`, `API_KEY=missing`, `INTRIC_API_KEY=missing`. |
| Runner readiness | `cd backend && uv run python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke ...` exits with `Missing ENEO_LOCAL_API_KEY or --api-key.` |

## Decision

Do not run live eval with pasted command-line secrets or guessed keys. Continue when the owner exports:

```bash
export ENEO_LOCAL_API_BASE=http://localhost:8123
export ENEO_LOCAL_API_KEY="<local service key>"
```

Then run:

```bash
cd backend
uv run python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke --output-dir /tmp/material-efficiency-live-eval/<timestamp>-t060-smoke
uv run python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --runs 1 --apply --output-dir /tmp/material-efficiency-live-eval/<timestamp>-t060-create-suite
```

Raw outputs stay under `/tmp/material-efficiency-live-eval/` and must not be committed.
