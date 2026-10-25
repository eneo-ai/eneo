# Flows scale harness (MVP)

Scenario A (viewers at the web-next poll cadence) and B1 (text-flow run
throughput) against a production-shaped local stack: 3 gunicorn workers,
Postgres with `max_connections=400` and `pg_stat_statements`, the mock model
with a latency knob. The probe sidecar and scenarios B2, C and D are not built
yet.

The stack is `docker-compose.e2e.ci.yml` plus `docker-compose.scale.yml`, under
its own project (`eneo-scale`), network (`eneo-scale`), images
(`eneo-scale-backend`, `eneo-scale-tools`) and host ports (API `8125`, Postgres
`55432`, mock `58200`). It never touches another checkout's `eneo-e2e` stack.

## Commands (from the repo root)

```bash
# A function, not S="-f ... -f ...": zsh does not word-split $S.
scale_compose() { docker compose -f docker-compose.e2e.ci.yml -f e2e/scale/docker-compose.scale.yml "$@"; }
PY=backend/.venv/bin/python        # httpx + asyncpg
git rev-parse HEAD; git status --short   # the image bakes in the working tree

# Up (first build takes a few minutes). Knobs are compose env:
#   M (TASK_EXECUTION_MAX_JOBS, default 4), RUN_CAP (per-tenant run cap, default 1000),
#   MOCK_LATENCY_MS (default 0), API_WORKERS (3), API_CPUS (3), WORKER_CPUS (1), DB_CPUS (1.5)
# A second scale stack: SCALE_PROJECT (default eneo-scale; also the network and image prefix)
# and SCALE_API_PORT / SCALE_DB_PORT / SCALE_MOCK_PORT (8125 / 55432 / 58200). Export the same
# values to scale.py, which reads them for its --base/--dsn/--mock/--project defaults.
MOCK_LATENCY_MS=2000 scale_compose up -d --build --wait

$PY e2e/scale/scale.py seed        # text6/text10 flows -> e2e/scale/state.json
$PY e2e/scale/scale.py selftest    # percentile helper, failure bounds, window accounting (fakes, no stack)

# A: N viewers on K active text6 runs (10% on the runs list); 2 min warm-up, 3 min measured
$PY e2e/scale/scale.py viewers --n 20 --active-runs 4 --duration 180 --out e2e/scale/out/A20

# B1, closed loop: C runs in flight until COUNT settle. Open loop: --rate R creates/s instead.
$PY e2e/scale/scale.py runs --concurrency 8 --count 60 --flow text10 --out e2e/scale/out/B1-C8-L2000

# Change a knob by recreating only that service; the report reads it back from the container.
MOCK_LATENCY_MS=0 scale_compose up -d --wait --no-deps e2e-mock-model
M=16 scale_compose up -d --wait --no-deps task-execution-worker

$PY e2e/scale/scale.py report e2e/scale/out/A20   # re-render a result
scale_compose down -v                             # stack and data gone
```

Knob values in the report (M, run cap, mock latency, gunicorn workers, CPU caps,
backend image) come from `docker inspect` of the running containers, never from
scale.py's environment.

## What a scenario does

1. **Drain**: waits until no `flow_runs` are queued or running (`--drain-timeout`,
   default 600 s, then exits with an error), so earlier runs cannot leak in.
2. **Warm-up** (`--warmup`, default 120 s, 0 for none): the same load, thrown
   away. It opens the pools and pays asyncpg's type introspection (the harness
   also runs its own report query once before any window). Then drain again.
3. **Statements per route** (`--iso`, default 30 requests per route, 0 skips):
   with the worker idle, 10 warm reads then N sequential reads of one route at a
   time on the latest completed run; `pg_stat_statements` calls per request,
   split into utility statements (BEGIN/COMMIT/SET...), RI-trigger statements
   (counted under `track=all`) and the net, compared with the ceilings in
   `backend/tests/integration/flows/test_flow_run_read_statement_budget.py`.
   MISMATCH means the net differs from the space-member ceiling; the
   tenant-admin ceiling and the difference to it are shown beside it.
4. **Baseline** (`--baseline`, default 15 s): idle stack with the samplers on;
   each container's cgroup CPU rate here is subtracted from the window.
5. **Measured window**: `pg_stat_statements` and the mock counters reset, then
   viewers for `--duration` s, or runs until `--count` settle.
6. **Window end**: the moment the load stops, container CPU, `pg_stat_statements`,
   the mock counters and the window's runs (created before that moment, status
   at it) are read together and the samplers stop; only then is the report
   written, so its own work never enters the results. Runs a viewer scenario
   leaves executing are reported as running.

A scenario fails instead of hanging. A run create answered with anything but
201, 429 or a 5xx (a bad token, a missing flow) fails it at once; so does a
create still failing with 429/5xx/transport errors after `--create-timeout`
(default 300 s, one retry a second), a run that has not settled after
`--settle-timeout` (default 600 s), or a failed settle poll. In a warm-up the
retries stop quietly at its end. On a failure the clients, pool and samplers
close and no report is written.

## What a scenario records

`<out>/result.json` (raw) and `<out>/report.md`:

- client p50/p95/p99/max (nearest-rank, n beside each; rows with n < 20 are
  starred), req/s and status codes per route template (host-side httpx, one
  shared 128-connection pool as a stand-in for the BFF, so client pool waits
  count as latency; SSE on its own unlimited client). Every attempt is one
  sample and one code, a failed or timed-out one at its time to fail, so n,
  the codes and the request total agree. The SSE row has one sample per
  stream: the time to its headers, and its status, `<status> then <error>` if
  it dropped, or the error if it never connected;
- `/api/livez` latency every 250 ms (an event-loop lag proxy);
- runs created during the window, from `flow_runs` with their status as it
  ended (`percentile_disc`, i.e. nearest-rank): queue wait, duration, per-step
  overhead over the containers' mock latency, throughput; 429s and
  `Retry-After`;
- mock call counts per path (`GET :58200/stats`, reset at the window start);
- container CPU from cgroup `cpu.stat` `usage_usec` (via `docker exec`) read
  before and after the window: CPU-ms, % of one core, the baseline rate, and net
  CPU-ms per client request and per completed run; cgroup `memory.peak` (since
  container start);
- `pg_stat_activity` connection maxima; top 25 `pg_stat_statements` by total
  time (the harness's own SQL is tagged `/* scale-harness */` and left out);
  the last `/api/healthz/flows`.

Run production (B): closed loop keeps C runs in flight, and one settle poller
checks every waiting run every 0.1 s, so a slot refills about 0.1 s after its run
settles. Open loop creates R runs per second whatever the backlog; a 429 is a
rejection and is not retried.

Viewer model (from `run-page.tsx`, `run-progress.ts`, `runs-list.tsx`,
`use-jobs.tsx`): status + graph in parallel every 2 s for 30 s after the
progress signature last changed, 5 s up to 5 min, then 15 s; run detail + steps
on each signature change (their own queries, so they do not delay the next
tick); stop when the status no longer polls. Like TanStack `refetchInterval`,
the next tick is armed when the previous response arrives. List viewers
poll page 1 every 2 s. Every viewer holds one jobs SSE and polls `/jobs/`
every 30 s. All viewers share the seeded test user.

Flow steps are `pass_through` (one model call per step); `compose_text` is
deterministic and never calls the model.
