# T061 Live Smoke Still Blocked

## Verdict

Live AI Builder material-efficiency smoke still cannot run in this shell because the runner requires a Flow API key and `ENEO_LOCAL_API_KEY` is not present.

## Evidence

| Check | Result |
|---|---|
| Host environment | `ENEO_LOCAL_API_KEY=missing`, `ENEO_LOCAL_API_BASE=missing`, and no admin/super key variable is exported in the shell. |
| App container environment | `ENEO_LOCAL_API_KEY=missing`, `ENEO_LOCAL_API_BASE=missing`, `ENEO_SUPER_API_KEY=missing`, `API_KEY=missing`, and `INTRIC_API_KEY=missing`. |
| Repo env file inventory | `backend/.env` is present and contains an `ENEO_SUPER_API_KEY` assignment, but no `ENEO_LOCAL_API_KEY` assignment was found in the checked env files. Secret values were not printed. |
| Runner behavior | `uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke ...` exits with `Missing ENEO_LOCAL_API_KEY or --api-key.` |
| Runner contract | `docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py` reads `ENEO_LOCAL_API_BASE` and `ENEO_LOCAL_API_KEY` or explicit `--api-base` and `--api-key`, then sends the key as `X-API-Key`. |
| API-key creation path | `POST /api/v1/api-keys` requires session authentication plus the `API_KEYS` permission, and the existing live regression script requires an admin bearer token. No unauthenticated local seed command was found. |

## Decision

Do not alias `ENEO_SUPER_API_KEY` to `ENEO_LOCAL_API_KEY` or mutate the local database to invent a key. Continue when the owner exports a Flow API key in the shell:

```bash
export ENEO_LOCAL_API_BASE=http://localhost:8123
export ENEO_LOCAL_API_KEY="<local service key>"
```

Then rerun:

```bash
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --smoke --output-dir /tmp/material-efficiency-live-eval/<timestamp>-t061-smoke
uv run --directory backend python ../docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --all --runs 1 --apply --output-dir /tmp/material-efficiency-live-eval/<timestamp>-t061-create-suite
```

Raw live-eval outputs stay under `/tmp/material-efficiency-live-eval/` and must not be committed.
