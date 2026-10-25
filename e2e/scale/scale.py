#!/usr/bin/env python3
"""Flows scale harness (MVP: scenario A viewers, scenario B1 text-flow runs).

Runs on the host against the stack in e2e/scale/docker-compose.scale.yml and
needs only httpx and asyncpg (both in backend/.venv). See README.md.

  seed      build the text6/text10 flows over the API, write state.json
  viewers   scenario A: K active runs, N viewers polling at the web-next cadence
  runs      scenario B1: COUNT runs, closed loop (--concurrency C) or open loop (--rate R)
  report    re-render an output directory's result.json
  selftest  check the percentile helper, the failure bounds and the window accounting (fakes, no stack)

Every scenario: drain (no queued/running runs), warm-up load, drain, a per-route
statement pass with the worker idle, an idle CPU baseline with the samplers on,
then pg_stat_statements/mock reset and the measured window, whose counters are all
read together the moment its load stops. CPU comes from each container's cgroup
cpu.stat; knobs from the containers' own env (docker inspect).
Writes <out>/result.json plus <out>/report.md.
"""

import argparse
import asyncio
import contextlib
import io
import itertools
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import asyncpg
import httpx

HERE = Path(__file__).resolve().parent
API = "/api/v1"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The stack's seeded test login (docker-compose.e2e.ci.yml DEFAULT_USER_*).
EMAIL = os.environ.get("SCALE_EMAIL", "e2e@example.com")
PASSWORD = os.environ.get("SCALE_PASSWORD", "E2ePassword123!")
SUPER_KEY = os.environ.get("SCALE_SUPER_KEY", "scale-super-key-not-a-secret")
INPUT_TEXT = ("Scale test input sentence. " * 1900)[:50_000]  # 50 KB
TAG = "/* scale-harness */"  # marks the harness's own SQL so pg_stat_statements totals leave it out
# ...and asyncpg's pool-release reset (the backend's SQLAlchemy pool does not use it).
PGSS_MINE = ("query NOT ILIKE '%pg_stat%' AND query NOT LIKE '%scale-harness%'"
             " AND query NOT IN ('SELECT pg_advisory_unlock_all()', 'CLOSE ALL', 'UNLISTEN *', 'RESET ALL')")
ACTIVE = ["queued", "running"]
# backend/tests/integration/flows/test_flow_run_read_statement_budget.py _CEILINGS: (space member, tenant admin)
CEILINGS = {"status": (13, 13), "graph": (14, 14), "run detail": (19, 18), "steps": (19, 19), "runs list": (14, 14)}
SMALL_N = 20


def pct(xs, p):
    """Nearest-rank percentile."""
    xs = sorted(xs)
    return xs[max(0, math.ceil(p / 100 * len(xs)) - 1)] if xs else None


class Rec:
    """Client-side latency and outcome per route template: one sample and one code (the status, or the
    transport error's name) for every attempt, so failed and timed-out requests count like the rest."""

    def __init__(self):
        self.lat = defaultdict(list)
        self.codes = defaultdict(Counter)

    def add(self, route, ms, code):
        self.lat[route].append(ms)
        self.codes[route][code] += 1

    async def call(self, c, method, path, **kw):
        route = f"{method} {UUID_RE.sub('{id}', path.split('?')[0])}"
        t = time.perf_counter()
        try:
            r = await c.request(method, path, **kw)
            code = str(r.status_code)
        except httpx.HTTPError as exc:
            r, code = None, type(exc).__name__
        self.add(route, (time.perf_counter() - t) * 1000, code)
        return r


def ok(r, code=200):
    if r is None or r.status_code != code:
        raise SystemExit(f"unexpected response: {r and r.status_code} {r and r.text[:500]}")
    return r.json()


async def login(base):
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        r = await c.post(f"{API}/users/login/token/", data={"username": EMAIL, "password": PASSWORD})
        return ok(r)["access_token"]


def api_client(base, token, max_connections=128):
    return httpx.AsyncClient(
        base_url=base,
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(60, connect=10),
        limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_connections),
    )


# ---------------------------------------------------------------- seed


async def cmd_seed(a):
    rec = Rec()
    async with api_client(a.base, await login(a.base)) as c:
        caps = ok(await rec.call(c, "GET", f"{API}/flows/runs/status-capabilities/"))["statuses"]
        space = ok(await rec.call(c, "POST", f"{API}/spaces/", json={"name": f"scale-{uuid4().hex[:6]}"}), 201)["id"]
        flows = {}
        for name, n_steps in (("text6", 6), ("text10", 10)):
            body = {"space_id": space, "name": f"Scale {name} {uuid4().hex[:6]}", "description": "Scale harness."}
            fid = ok(await rec.call(c, "POST", f"{API}/flows/", json=body), 201)["id"]
            steps = []
            for i in range(1, n_steps + 1):
                asst = ok(await rec.call(c, "POST", f"{API}/flows/{fid}/assistants/", json={"name": f"{name} step {i}"}), 201)
                steps.append({
                    "assistant_id": asst["id"], "step_order": i, "user_description": f"Step {i}.",
                    "input_source": "flow_input" if i == 1 else "previous_step",
                    "input_type": "text", "output_mode": "pass_through", "output_type": "text",  # one model call
                })
            ok(await rec.call(c, "PATCH", f"{API}/flows/{fid}/", json={"name": body["name"], "description": body["description"], "steps": steps}))
            version = ok(await rec.call(c, "POST", f"{API}/flows/{fid}/publish/"))["published_version"]
            flows[name] = {"id": fid, "version": version, "steps": n_steps}
    state = {"space_id": space, "flows": flows, "poll_statuses": [s["status"] for s in caps if s["should_poll"]]}
    Path(a.state).write_text(json.dumps(state, indent=2))
    print(json.dumps(state, indent=2))


# ---------------------------------------------------------------- containers


def containers(project):
    rows = subprocess.run(
        ["docker", "ps", "--filter", f"label=com.docker.compose.project={project}",
         "--format", '{{.Label "com.docker.compose.service"}} {{.ID}}'],
        capture_output=True, text=True, check=True,
    ).stdout.split("\n")
    found = dict(r.split() for r in rows if r.strip())
    if "e2e-backend" not in found:
        raise SystemExit(f"no running e2e-backend in compose project {project!r} (--project / SCALE_PROJECT)")
    return found


def knobs(ctrs):
    """The values the running containers were started with, not scale.py's env."""
    info = {i["Config"]["Labels"]["com.docker.compose.service"]: i for i in json.loads(subprocess.run(
        ["docker", "inspect", *ctrs.values()], capture_output=True, text=True, check=True).stdout)}
    env = {s: dict(e.split("=", 1) for e in i["Config"]["Env"]) for s, i in info.items()}
    cmd = " ".join(info["e2e-backend"]["Config"]["Cmd"] or [])
    workers = re.search(r"--workers\s+(\d+)", cmd)
    return {
        "M (TASK_EXECUTION_MAX_JOBS)": env.get("task-execution-worker", {}).get("TASK_EXECUTION_MAX_JOBS"),
        "RUN_CAP (FLOW_MAX_CONCURRENT_RUNS_PER_TENANT)": env["e2e-backend"].get("FLOW_MAX_CONCURRENT_RUNS_PER_TENANT"),
        "MOCK_LATENCY_MS": env.get("e2e-mock-model", {}).get("MOCK_LATENCY_MS", "0"),
        "MOCK_LATENCY_JITTER_MS": env.get("e2e-mock-model", {}).get("MOCK_LATENCY_JITTER_MS", "0"),
        "gunicorn workers": workers and workers.group(1),
        "cpus": {s: (i["HostConfig"]["NanoCpus"] or 0) / 1e9 or None for s, i in sorted(info.items())},
        "backend image": info["e2e-backend"]["Image"][7:19],
    }


async def cgroup(ctrs):
    """cpu.stat usage_usec and memory.peak per container, read through docker exec."""
    async def one(cid):
        p = await asyncio.create_subprocess_exec(
            "docker", "exec", cid, "sh", "-c", "cat /sys/fs/cgroup/cpu.stat; cat /sys/fs/cgroup/memory.peak 2>/dev/null || true",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        lines = (await p.communicate())[0].decode().split("\n")
        kv = dict(x.split() for x in lines if len(x.split()) == 2)
        peak = [x for x in lines if x.strip().isdigit()]
        return {"usage_usec": int(kv["usage_usec"]) if "usage_usec" in kv else None, "mem_peak": int(peak[0]) if peak else None}
    vals = await asyncio.gather(*(one(c) for c in ctrs.values()))
    return {"t": time.monotonic(), "c": dict(zip(ctrs, vals))}


def cpu_ms(c0, c1):
    """CPU-ms per container between two cgroup reads, and the window in seconds."""
    return {s: (v["usage_usec"] - c0["c"][s]["usage_usec"]) / 1000 for s, v in c1["c"].items()
            if v["usage_usec"] is not None and c0["c"].get(s, {}).get("usage_usec") is not None}, c1["t"] - c0["t"]


# ---------------------------------------------------------------- samplers


async def sample_livez(base, out):
    async with httpx.AsyncClient(base_url=base, timeout=10) as c:
        while True:
            t = time.perf_counter()
            try:
                await c.get("/api/livez")
                out.append((time.perf_counter() - t) * 1000)
            except httpx.HTTPError:
                out.append(None)
            await asyncio.sleep(0.25)


async def sample_pg(pool, out):
    while True:
        row = await pool.fetchrow(
            "SELECT count(*) AS total, count(*) FILTER (WHERE state = 'active') AS active,"
            " count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx,"
            " count(*) FILTER (WHERE wait_event_type = 'Lock') AS lock_waits"
            " FROM pg_stat_activity WHERE datname = current_database()"
        )
        out.append(dict(row))
        await asyncio.sleep(2)


async def sample_health(base, out):
    async with httpx.AsyncClient(base_url=base, timeout=30, headers={"X-API-Key": SUPER_KEY}) as c:
        while True:
            t = time.perf_counter()
            try:
                r = await c.get("/api/healthz/flows")
                out.append({"ms": (time.perf_counter() - t) * 1000, "code": r.status_code, "body": r.json()})
            except (httpx.HTTPError, ValueError) as exc:
                out.append({"error": repr(exc)})
            await asyncio.sleep(10)


# ---------------------------------------------------------------- scenario frame


class Settle:
    """One 0.1 s DB poll for every run a producer waits on, so worker slots are not left idle. A wait
    fails after `timeout` s, and every wait, current or later, fails once the poll itself has failed."""

    def __init__(self, pool, poll, timeout):
        self.pool, self.poll, self.timeout, self.waiting, self.error = pool, list(poll), timeout, {}, None

    async def wait(self, run_id):
        if self.error:
            raise self.error
        fut = self.waiting[run_id] = asyncio.get_running_loop().create_future()
        try:
            done, _ = await asyncio.wait([fut], timeout=self.timeout)
        finally:
            self.waiting.pop(run_id, None)
        if not done:
            raise RuntimeError(f"run {run_id} did not settle in {self.timeout:g} s (--settle-timeout)")
        fut.result()  # the poll's error, if it failed

    async def run(self):
        try:
            while True:
                if self.waiting:
                    rows = await self.pool.fetch(
                        f"SELECT {TAG} id::text FROM flow_runs WHERE id = ANY($1::uuid[]) AND status::text <> ALL($2::text[])",
                        list(self.waiting), self.poll)
                    for r in rows:
                        fut = self.waiting.pop(r["id"], None)  # None: that wait timed out during the fetch
                        if fut and not fut.done():
                            fut.set_result(None)
                await asyncio.sleep(0.1)
        except Exception as exc:
            self.error = exc
            for fut in self.waiting.values():
                if not fut.done():
                    fut.set_exception(exc)
            raise


async def drain(pool, timeout):
    t = time.monotonic()
    while n := await pool.fetchval(f"SELECT {TAG} count(*) FROM flow_runs WHERE status::text = ANY($1::text[])", ACTIVE):
        if time.monotonic() - t > timeout:
            raise SystemExit(f"{n} flow_runs still queued/running after {timeout:.0f} s; they would leak into the"
                             " window. Wait, cancel them, or raise --drain-timeout.")
        await asyncio.sleep(1)


async def create_run(c, rec, flow, runs, retry_for, deadline=math.inf):
    """POST a run: its id, or None once it failed and `retry_for` is None (no retry) or `deadline` has
    passed. A 429, 5xx or transport error is retried every second for up to `retry_for` s; any other status
    (a bad token, a missing flow) or running out of retries ends the scenario."""
    give_up = time.monotonic() + (retry_for or 0)
    while True:
        r = await rec.call(c, "POST", f"{API}/flows/{flow['id']}/runs/", json={
            "expected_flow_version": flow["version"], "input_payload_json": {"text": INPUT_TEXT},
        })
        runs["create"]["error" if r is None else str(r.status_code)] += 1
        if r is not None and r.status_code == 201:
            return r.json()["id"]
        if r is not None and r.status_code == 429:
            runs["retry_after"].append(r.headers.get("Retry-After"))
        elif r is not None and r.status_code < 500:
            raise RuntimeError(f"run create: unexpected {r.status_code} {r.text[:300]}")
        if retry_for is None or time.monotonic() >= deadline:
            return None
        if time.monotonic() >= give_up:
            raise RuntimeError(f"no run created in {retry_for:g} s of retries (--create-timeout): {dict(runs['create'])}")
        await asyncio.sleep(1)


async def run_for(coros, seconds=None):
    """Run coros until they all return or `seconds` pass; the first error cancels the rest and is raised."""
    with contextlib.suppress(TimeoutError):  # a coro's own TimeoutError arrives inside an ExceptionGroup
        async with asyncio.timeout(seconds), asyncio.TaskGroup() as tg:
            for x in coros:
                tg.create_task(x)


async def statements_per_route(c, pool, flow_id, n):
    """Warm sequential reads of one route at a time, worker idle (after a drain): the most common
    pg_stat_statements call count per request, split into the utility and RI-trigger statements the
    budget test's SQLAlchemy listener never sees and the rest."""
    run = await pool.fetchval(
        f"SELECT {TAG} id::text FROM flow_runs WHERE flow_id = $1 AND status::text = 'completed'"
        " ORDER BY created_at DESC LIMIT 1", flow_id)
    if run is None:
        return {"skipped": "no completed run of this flow yet (use a warm-up)"}
    base = f"{API}/flows/{flow_id}"
    routes = {"status": f"{base}/runs/{run}/status/", "graph": f"{base}/graph/?run_id={run}",
              "run detail": f"{base}/runs/{run}/", "steps": f"{base}/runs/{run}/steps/",
              "runs list": f"{base}/runs/?limit=25&offset=0&sort=started_at&order=desc"}
    out = {}
    for route, url in routes.items():
        for _ in range(10):  # every gunicorn worker's caches and pooled connections
            ok(await c.get(url))
        per = []
        for _ in range(n):  # one request per reset, so a rare cache refresh cannot shift the count
            await pool.execute("SELECT pg_stat_statements_reset()")
            ok(await c.get(url))
            await asyncio.sleep(0.05)
            row = await pool.fetchrow(
                "SELECT coalesce(sum(calls), 0)::int AS total,"
                r" coalesce(sum(calls) FILTER (WHERE query ~* '^\s*(BEGIN|COMMIT|ROLLBACK|START|SAVEPOINT|RELEASE|SET|RESET|SHOW|DISCARD)\M'), 0)::int AS utility,"
                " coalesce(sum(calls) FILTER (WHERE query LIKE '%OPERATOR(pg_catalog.=)%FOR KEY SHARE OF%'), 0)::int AS ri_nested"
                f" FROM pg_stat_statements WHERE {PGSS_MINE}")
            per.append((row["total"], row["utility"], row["ri_nested"]))
        (total, utility, ri), seen = Counter(per).most_common(1)[0]
        out[route] = {"total": total, "utility": utility, "ri_nested": ri, "mode_n": seen, "n": n,
                      "mean_total": sum(x[0] for x in per) / n}
    return out


RUN_SQL = (  # runs created in the window [$1, $2), status as read at its end
    f"SELECT {TAG} status::text, count(*) AS n,"
    " percentile_disc(array[.5,.95]) WITHIN GROUP (ORDER BY extract(epoch FROM started_at - created_at)) AS queue_wait_s,"
    " percentile_disc(array[.5,.95]) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at)) AS duration_s,"
    " extract(epoch FROM max(finished_at) - min(created_at)) AS span_s"
    " FROM flow_runs WHERE created_at >= $1 AND created_at < $2 GROUP BY status"
)
PGSS_TOP = (
    "SELECT left(regexp_replace(query, '\\s+', ' ', 'g'), 140) AS query, calls,"
    " round(total_exec_time::numeric, 1) AS total_ms, round(mean_exec_time::numeric, 3) AS mean_ms, rows"
    f" FROM pg_stat_statements WHERE {PGSS_MINE} ORDER BY total_exec_time DESC LIMIT 25"
)
PGSS_TOTAL = f"SELECT sum(calls) AS calls, round(sum(total_exec_time)::numeric, 1) AS total_ms FROM pg_stat_statements WHERE {PGSS_MINE}"


async def snapshot(pool, ctrs, mock_url, t0):
    """Every counter of the window, read together the moment its load stops: container CPU, its runs (cut
    off at that moment, status then), pg_stat_statements and the mock's calls. The report reads only this."""
    async def db():
        t1 = await pool.fetchval(f"SELECT {TAG} now()")
        return await pool.fetch(RUN_SQL, t0, t1), await pool.fetch(PGSS_TOP), await pool.fetchrow(PGSS_TOTAL)
    return await asyncio.gather(cgroup(ctrs), db(), asyncio.to_thread(lambda: httpx.get(f"{mock_url}/stats").json()))


async def scenario(a, name, body):
    state = json.loads(Path(a.state).read_text())
    flow_id = state["flows"][a.flow]["id"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ctrs = containers(a.project)
    knob = knobs(ctrs)
    print(f"knobs: {json.dumps(knob)}", flush=True)
    pool = await asyncpg.create_pool(a.dsn, min_size=2, max_size=4)
    settle = Settle(pool, state["poll_statuses"], a.settle_timeout)
    bg = [asyncio.create_task(settle.run())]
    livez, pg, health = [], [], []
    try:
        await pool.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
        now = await pool.fetchval(f"SELECT {TAG} now()")
        await pool.fetch(RUN_SQL, now, now)  # asyncpg type introspection, before any window
        token = await login(a.base)
        async with api_client(a.base, token) as c, api_client(a.base, token, max_connections=None) as sse:
            await drain(pool, a.drain_timeout)
            if a.warmup:
                print(f"warm-up {a.warmup:.0f} s", flush=True)
                await body(a, state, c, sse, Rec(), {"create": Counter(), "retry_after": []}, settle, True)
                await drain(pool, a.drain_timeout)
            iso = await statements_per_route(c, pool, flow_id, a.iso) if a.iso else {}
            bg += [asyncio.create_task(x) for x in (sample_livez(a.base, livez), sample_pg(pool, pg), sample_health(a.base, health))]
            b0 = await cgroup(ctrs)
            await asyncio.sleep(a.baseline)  # idle stack, samplers on: their cost and the idle rate
            b1 = await cgroup(ctrs)
            await pool.execute("SELECT pg_stat_statements_reset()")
            db_t0 = await pool.fetchval(f"SELECT {TAG} now()")
            httpx.get(f"{a.mock}/stats?reset=1").raise_for_status()
            livez.clear()
            pg.clear()
            rec, runs = Rec(), {"create": Counter(), "retry_after": []}
            print(f"measuring ({name})", flush=True)
            w0 = await cgroup(ctrs)
            await body(a, state, c, sse, rec, runs, settle, False)
            w1, (run_rows, pgss, pgss_total), mock_stats = await snapshot(pool, ctrs, a.mock, db_t0)
    finally:  # the samplers stop with the window, and on any failure the pool and poller go too
        for t in bg:
            t.cancel()
        await asyncio.gather(*bg, return_exceptions=True)
        await pool.close()
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=HERE).stdout.strip())
    base_ms, base_s = cpu_ms(b0, b1)
    win_ms, wall = cpu_ms(w0, w1)
    result = {
        "scenario": name, "args": {k: v for k, v in vars(a).items() if k != "func"}, "wall_s": wall,
        "revision": rev + ("-dirty" if dirty else ""), "knobs": knob,
        "latency_ms": rec.lat, "codes": rec.codes, "runs": runs,
        "run_sql": [{k: [None if x is None else float(x) for x in v] if isinstance(v, list) else v
                     for k, v in dict(r).items()} for r in run_rows],
        "mock_stats": mock_stats,
        "livez_ms": livez, "pg_activity": pg, "health": health[-1:],
        "cpu": {"baseline_ms": base_ms, "baseline_s": base_s, "window_ms": win_ms,
                "mem_peak": {s: v["mem_peak"] for s, v in w1["c"].items()}},
        "statements_per_route": iso,
        "pgss_top": [dict(r) for r in pgss], "pgss_total": dict(pgss_total),
        "steps": state["flows"][a.flow]["steps"],
    }
    (out / "result.json").write_text(json.dumps(result, default=str))
    text = render(json.loads(json.dumps(result, default=str)))
    (out / "report.md").write_text(text)
    print(text)


# ---------------------------------------------------------------- A: viewers


async def viewers_body(a, state, c, sse, rec, runs, settle, warm):
    flow, poll = state["flows"][a.flow], set(state["poll_statuses"])
    fid = flow["id"]
    n_list = a.n // 10
    n_page = a.n - n_list

    async def run_viewer(run):  # run-page.tsx + run-status.ts + run-progress.ts
        await asyncio.sleep(random.uniform(0, 2))  # viewers do not arrive in lockstep
        sig, changed, reads = None, time.monotonic(), set()

        async def reread(status):  # detail/steps are their own queries, keyed by the signature
            await asyncio.gather(
                rec.call(c, "GET", f"{API}/flows/{fid}/runs/{run}/"),
                rec.call(c, "GET", f"{API}/flows/{fid}/runs/{run}/steps/"),
            )
            if status == "awaiting_review":
                await rec.call(c, "GET", f"{API}/flows/{fid}/runs/{run}/review-checkpoints/active/")

        try:
            while True:
                st, gr = await asyncio.gather(  # one progress query: Promise.all(status, graph)
                    rec.call(c, "GET", f"{API}/flows/{fid}/runs/{run}/status/"),
                    rec.call(c, "GET", f"{API}/flows/{fid}/graph/?run_id={run}"),
                )
                if st is None or st.status_code != 200 or gr is None or gr.status_code != 200:
                    await asyncio.sleep(2)
                    continue
                st, gr = st.json(), gr.json()
                s = (st["revision"], st["status"], tuple(
                    (n["step_order"], n.get("run_status")) for n in gr["nodes"] if n.get("step_order") is not None))
                if s != sig:
                    sig, changed = s, time.monotonic()
                    t = asyncio.create_task(reread(st["status"]))
                    reads.add(t)
                    t.add_done_callback(reads.discard)
                if st["status"] not in poll:
                    await asyncio.gather(*reads)
                    return
                age = time.monotonic() - changed
                # TanStack refetchInterval re-arms when the fetch settles, so the delay runs from the response.
                await asyncio.sleep(2 if age < 30 else 5 if age < 300 else 15)
        finally:
            for t in reads:
                t.cancel()

    async def slot(i):  # keeps one run active, its run-page viewers attached
        mine = range(i, n_page, a.active_runs)
        while True:
            run = await create_run(c, rec, flow, runs, a.create_timeout)
            await (asyncio.gather(*(run_viewer(run) for _ in mine)) if mine else settle.wait(run))

    async def list_viewer():  # runs-list.tsx; ponytail: fixed 2 s band, the list always has an active run
        await asyncio.sleep(random.uniform(0, 2))
        while True:
            await rec.call(c, "GET", f"{API}/flows/{fid}/runs/?limit=25&offset=0&sort=started_at&order=desc")
            await asyncio.sleep(2)

    async def tab():  # JobsProvider: one held SSE + GET /jobs/ every 30 s
        async def hold():  # one sample per stream: ms to its headers (or to its error), and how it ended
            route = f"SSE {API}/jobs/events/ (connect)"
            while True:
                t, got = time.perf_counter(), None
                try:
                    async with sse.stream("GET", f"{API}/jobs/events/", headers={"Accept": "text/event-stream"},
                                          timeout=httpx.Timeout(10, read=None)) as r:
                        got = ((time.perf_counter() - t) * 1000, str(r.status_code))
                        async for _ in r.aiter_lines():
                            pass
                except httpx.HTTPError as exc:  # no headers, or a stream that dropped
                    err = type(exc).__name__
                    got = (got[0], f"{got[1]} then {err}") if got else ((time.perf_counter() - t) * 1000, err)
                finally:
                    if got:  # cancelled before its headers is no attempt, as in Rec.call
                        rec.add(route, *got)
                await asyncio.sleep(1)

        async def jobs():
            await asyncio.sleep(random.uniform(0, 30))
            while True:
                await rec.call(c, "GET", f"{API}/jobs/")
                await asyncio.sleep(30)

        await run_for([hold(), jobs()])

    coros = [slot(i) for i in range(a.active_runs)] + [list_viewer() for _ in range(n_list)] + [tab() for _ in range(a.n)]
    await run_for(coros, a.warmup if warm else a.duration)


# ---------------------------------------------------------------- B: runs


async def runs_body(a, state, c, sse, rec, runs, settle, warm):
    """Closed loop: C producers, each creates a run and waits for it to settle. Open loop: one create
    every 1/R s whatever the backlog, a 429 is a rejection (no retry). Warm-up: same shape for --warmup s."""
    flow = state["flows"][a.flow]
    deadline = time.monotonic() + (a.warmup if warm else math.inf)
    left = [math.inf if warm else a.count]

    def more():
        if left[0] <= 0 or time.monotonic() >= deadline:
            return False
        left[0] -= 1
        return True

    if a.rate:
        async def one():
            if run := await create_run(c, rec, flow, runs, None):
                await settle.wait(run)

        async with asyncio.TaskGroup() as tg:  # a failed create or settle stops the schedule at once
            due = time.monotonic()
            while more():
                tg.create_task(one())
                due += 1 / a.rate
                await asyncio.sleep(max(0, due - time.monotonic()))
        return

    async def producer():
        while more():
            run = await create_run(c, rec, flow, runs, a.create_timeout, deadline)
            if run is None:  # the warm-up ended while it retried
                return
            await settle.wait(run)

    await run_for(producer() for _ in range(a.concurrency))


# ---------------------------------------------------------------- report


def render(r):
    f = lambda v: "-" if v is None else f"{float(v):.0f}" if float(v) >= 100 else f"{float(v):.1f}"  # noqa: E731
    nf = lambda n: f"{n}*" if n < SMALL_N else str(n)  # noqa: E731
    wall, args = r["wall_s"], r["args"]
    mode = (f"open loop R={args['rate']}/s" if args.get("rate") else f"closed loop C={args['concurrency']}") \
        if "count" in args else f"N={args['n']} viewers, K={args['active_runs']} active runs"
    lines = [
        f"# {r['scenario']} ({r['revision']})", "",
        f"mode: {mode}; warm-up {args['warmup']:.0f} s, then drain, statement pass, {args['baseline']:.0f} s idle baseline, measured window  ",
        f"args: `{json.dumps({k: v for k, v in args.items() if k not in ('dsn', 'state')})}`  ",
        f"wall (measured window): {wall:.1f} s", "",
        "## Knobs (from the running containers: docker inspect)", "",
        *[f"- {k}: `{v}`" for k, v in r["knobs"].items()], "",
        f"## Client latency per route (ms, measured on the host, every attempt: errors and timeouts at their time to fail; nearest-rank; * = n < {SMALL_N}, percentiles unreliable)", "",
        "| route | n | req/s | p50 | p95 | p99 | max | codes |", "|---|---|---|---|---|---|---|---|",
    ]
    total = 0
    for route in sorted(set(r["latency_ms"]) | set(r["codes"])):
        xs = r["latency_ms"].get(route, [])
        total += len(xs)
        codes = ", ".join(f"{k}:{v}" for k, v in sorted(r["codes"].get(route, {}).items()))
        lines.append(f"| `{route}` | {nf(len(xs))} | {len(xs) / wall:.2f} | {f(pct(xs, 50))} | {f(pct(xs, 95))} | "
                     f"{f(pct(xs, 99))} | {f(max(xs) if xs else None)} | {codes} |")
    live = [x for x in r["livez_ms"] if x is not None]
    lines += [
        "", f"total client requests: {total} ({total / wall:.1f} req/s)  ",
        f"livez (every 250 ms, n={nf(len(live))}, failed={len(r['livez_ms']) - len(live)}): "
        f"p50 {f(pct(live, 50))} / p95 {f(pct(live, 95))} / p99 {f(pct(live, 99))} / max {f(max(live) if live else None)} ms",
        "", "## Runs (flow_runs created during the window, status as it ended; percentile_disc = nearest-rank)", "",
        f"create: `{json.dumps(r['runs']['create'])}`, 429 Retry-After: `{sorted(set(map(str, r['runs']['retry_after'])))}`", "",
        "| status | n | queue wait p50/p95 s | duration p50/p95 s | first create to last finish s |", "|---|---|---|---|---|",
    ]
    lat_ms = float(r["knobs"].get("MOCK_LATENCY_MS") or 0)
    completed = 0
    for row in r["run_sql"]:
        q, d = row["queue_wait_s"] or [None, None], row["duration_s"] or [None, None]
        lines.append(f"| {row['status']} | {nf(row['n'])} | {f(q[0])} / {f(q[1])} | {f(d[0])} / {f(d[1])} | {f(row['span_s'])} |")
        if row["status"] == "completed" and d[0] is not None:
            completed = row["n"]
            per_step = float(d[0]) / r["steps"]
            lines.append(f"|  | per step p50 {per_step:.2f} s, overhead over the {lat_ms:.0f} ms mock latency {per_step - lat_ms / 1000:.2f} s | | | |")
            if row["span_s"]:
                lines.append(f"|  | throughput {row['n'] / float(row['span_s']) * 60:.1f} runs/min over the span | | | |")
    cpu = r["cpu"]
    lines += ["", f"mock calls: `{json.dumps(r['mock_stats'])}`", "",
              "## Container CPU (cgroup cpu.stat usage_usec, read before and after the window)", "",
              f"Baseline: {cpu['baseline_s']:.1f} s of idle stack with the samplers running (livez 4/s, pg_stat_activity 0.5/s,"
              " healthz 0.1/s). Net = window CPU minus baseline rate x wall, so the samplers and idle cost are out.", "",
              "| container | window CPU-ms | % of one core | baseline CPU-ms/s | net CPU-ms | net CPU-ms per client request "
              "| net CPU-ms per completed run | memory.peak MiB |", "|---|---|---|---|---|---|---|---|"]
    for s, ms in sorted(cpu["window_ms"].items()):
        rate = cpu["baseline_ms"].get(s, 0) / cpu["baseline_s"] if cpu["baseline_s"] else 0
        net = ms - rate * wall
        peak = cpu["mem_peak"].get(s)
        lines.append(f"| {s} | {ms:.0f} | {ms / wall / 10:.1f} | {rate:.1f} | {net:.0f} | {f(net / total) if total else '-'} | "
                     f"{f(net / completed) if completed else '-'} | {f(peak / 2**20) if peak else '-'} |")
    if r["pg_activity"]:
        lines += ["", "pg_stat_activity max: " + ", ".join(
            f"{k} {max(s[k] for s in r['pg_activity'])}" for k in r["pg_activity"][0])]
    iso = r["statements_per_route"]
    lines += ["", "## Statements per route (isolated pass, worker idle, warm, sequential)", ""]
    if "skipped" in iso or not iso:
        lines.append(f"skipped: {iso.get('skipped', 'disabled (--iso 0)')}")
    else:
        lines += ["pg_stat_statements calls of one request (pgss reset before each; the most common count over n, and how"
                  " often it occurred). Net leaves out utility statements (BEGIN/COMMIT/SET...) and RI-trigger statements"
                  " (track=all), which the budget test's SQLAlchemy listener never sees. Ceilings from"
                  " test_flow_run_read_statement_budget.py; the harness user is the tenant owner who created the space.", "",
                  "| route | mode in n | mean all | all | utility | RI nested | net | member ceiling | verdict | tenant-admin ceiling |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for route, v in iso.items():
            net = v["total"] - v["utility"] - v["ri_nested"]
            mem, adm = CEILINGS[route]
            lines.append(f"| {route} | {v['mode_n']}/{v['n']} | {v['mean_total']:.2f} | {v['total']} | {v['utility']} | "
                         f"{v['ri_nested']} | {net} | {mem} | {'ok' if net == mem else 'MISMATCH'} | "
                         f"{adm}{'' if net == adm else f' (net {net - adm:+d})'} |")
    lines += ["", f"## pg_stat_statements top 25 by total time (all: {r['pgss_total']['calls']} calls, "
              f"{r['pgss_total']['total_ms']} ms; harness SQL left out)", "", "| total ms | calls | mean ms | rows | query |", "|---|---|---|---|---|"]
    for q in r["pgss_top"]:
        lines.append(f"| {q['total_ms']} | {q['calls']} | {q['mean_ms']} | {q['rows']} | `{q['query'].replace('|', '/')}` |")
    if r["health"]:
        lines += ["", f"last /api/healthz/flows: `{json.dumps(r['health'][-1])[:600]}`"]
    return "\n".join(lines) + "\n"


def cmd_report(a):
    print(render(json.loads((Path(a.out) / "result.json").read_text())))


# ---------------------------------------------------------------- selftest (fakes, no stack)

STATE = {"space_id": "s", "flows": {"f": {"id": "f", "version": 1, "steps": 1}}, "poll_statuses": ["queued", "running"]}


class FakePool:
    """Answers scale.py's queries without a database. Once `late` (a list) is non-empty, i.e. the window
    is over, its runs have finished and its statement count has moved on."""

    def __init__(self, late=(), fail=None):
        self.late, self.fail = late, fail

    async def fetch(self, sql, *_):
        if self.fail:
            raise self.fail
        if sql != RUN_SQL:
            return []  # settle polls never settle; no top statements
        return [{"status": "completed" if self.late else "running", "n": 1, "queue_wait_s": None, "duration_s": None, "span_s": None}]

    async def fetchrow(self, *_):
        return {"calls": 9 if self.late else 1, "total_ms": 1.0}

    async def fetchval(self, *_):
        return 0  # drain: nothing active; now(): a value only this fake reads

    async def execute(self, *_):
        pass

    async def close(self):
        pass


async def ends(coro, within):
    """The error coro ends with (a TaskGroup's first), or None; it must end within `within` s."""
    try:
        async with asyncio.timeout(within) as cm:
            await coro
    except ExceptionGroup as eg:
        return eg.exceptions[0]
    except Exception as exc:
        assert not cm.expired(), f"still running after {within} s"
        return exc
    return None


async def check_create_bounds():
    """A permanent create rejection ends the closed loop at once; retried failures end it at
    --create-timeout, or quietly at the warm-up's deadline."""
    for status, kw, warm, want, within in ((401, {}, False, "unexpected 401", 0.5),
                                           (503, {"create_timeout": 0.5}, False, "--create-timeout", 3),
                                           (503, {"create_timeout": 0}, False, "--create-timeout", 0.5),
                                           (503, {"warmup": 0.5}, True, None, 3)):
        a = argparse.Namespace(**{"rate": None, "concurrency": 3, "count": 10, "warmup": 0, "create_timeout": 60, "flow": "f", **kw})
        async with httpx.AsyncClient(base_url="http://scale.test", transport=httpx.MockTransport(lambda _, s=status: httpx.Response(s))) as c:
            err = await ends(runs_body(a, STATE, c, None, Rec(), {"create": Counter(), "retry_after": []}, None, warm), within)
        assert (want in str(err)) if want else err is None, (status, kw, err)


async def check_settle_failures():
    """A failed settle poll fails its waiter and every later one at once; a run that never settles times out."""
    for pool, want in ((FakePool(fail=OSError("db gone")), "db gone"), (FakePool(), "did not settle")):
        settle = Settle(pool, ["queued"], 0.3)
        poller = asyncio.create_task(settle.run())
        assert want in str(await ends(settle.wait("r1"), 2)) and not settle.waiting, want
        if pool.fail:
            assert want in str(await ends(settle.wait("r2"), 0.05))
        poller.cancel()
        await asyncio.gather(poller, return_exceptions=True)


async def check_window_accounting():
    """Every attempt counts once, a timed-out one too, and the window's counters are read as its load stops:
    a slow report preparation, while its runs finish and statements keep counting, changes nothing."""
    late, attempts = [], itertools.count()

    def api(req):  # every other request times out
        if next(attempts) % 2:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json={})

    async def body(a, state, c, sse, rec, runs, settle, warm):
        for _ in range(5):
            await rec.call(c, "GET", f"{API}/flows/")

    class Client(httpx.AsyncClient):  # its close is the first step after the window: the stack moves on
        async def __aexit__(self, *exc):
            late.append(1)
            return await super().__aexit__(*exc)

    def git(*args, **_):  # a slow report preparation
        time.sleep(0.25)
        return subprocess.CompletedProcess(args, 0, "selftest", "")

    def mock_get(url, **_):
        return httpx.Response(200, json={"/v1/chat/completions": 9 if late else 1}, request=httpx.Request("GET", url))

    async def pool(*_, **__):
        return FakePool(late)

    async def token(_base):
        return "token"

    async def idle(*_):
        await asyncio.Event().wait()

    with tempfile.TemporaryDirectory() as out, patch.multiple(sys.modules[__name__], containers=lambda _: {}, knobs=lambda _: {}, login=token, sample_livez=idle,
                        sample_pg=idle, sample_health=idle,
                        api_client=lambda base, *_, **__: Client(base_url=base, transport=httpx.MockTransport(api))), \
            patch.object(asyncpg, "create_pool", pool), patch.object(httpx, "get", mock_get), \
            patch.object(subprocess, "run", git), contextlib.redirect_stdout(io.StringIO()):
        (Path(out) / "state.json").write_text(json.dumps(STATE))
        await scenario(argparse.Namespace(
            state=f"{out}/state.json", flow="f", out=out, project="p", dsn="", base="http://scale.test", mock="http://mock.test",
            drain_timeout=1, warmup=0, iso=0, baseline=0, create_timeout=1, settle_timeout=1, n=1, active_runs=1), "selftest", body)
        r, report = json.loads((Path(out) / "result.json").read_text()), (Path(out) / "report.md").read_text()
    route = f"GET {API}/flows/"
    assert len(r["latency_ms"][route]) == 5 and r["codes"][route] == {"200": 3, "ReadTimeout": 2}, r["codes"]
    assert "total client requests: 5 (" in report
    assert [x["status"] for x in r["run_sql"]] == ["running"], r["run_sql"]
    assert r["mock_stats"] == {"/v1/chat/completions": 1} and r["pgss_total"]["calls"] == 1, (r["mock_stats"], r["pgss_total"])
    assert r["wall_s"] < 0.2, r["wall_s"]


def cmd_selftest(_a):
    assert pct([30, 88, 1, 2], 50) == 2  # nearest-rank: the 2nd of 4, not the upper middle
    assert pct(range(1, 101), 99) == 99 and pct(range(1, 101), 100) == 100 and pct(range(1, 51), 99) == 50
    assert pct([7], 50) == 7 and pct([], 50) is None
    for check in (check_create_bounds, check_settle_failures, check_window_accounting):
        asyncio.run(check())
    print("ok")


def main():
    env = os.environ.get
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default=f"http://localhost:{env('SCALE_API_PORT', '8125')}")
    p.add_argument("--dsn", default=f"postgresql://postgres:postgres@localhost:{env('SCALE_DB_PORT', '55432')}/eneo_test")
    p.add_argument("--mock", default=f"http://localhost:{env('SCALE_MOCK_PORT', '58200')}")
    p.add_argument("--project", default=env("SCALE_PROJECT", "eneo-scale"))
    p.add_argument("--state", default=str(HERE / "state.json"))
    sub = p.add_subparsers(required=True)
    sub.add_parser("seed").set_defaults(func=lambda a: asyncio.run(cmd_seed(a)))

    def frame(sp):
        sp.add_argument("--out", required=True)
        sp.add_argument("--warmup", type=float, default=120, help="seconds of the same load before measuring (0 = none)")
        sp.add_argument("--drain-timeout", type=float, default=600, help="max wait for queued/running runs to settle")
        sp.add_argument("--create-timeout", type=float, default=300,
                        help="max seconds a run create is retried on 429/5xx/transport errors before the scenario fails")
        sp.add_argument("--settle-timeout", type=float, default=600, help="max wait for one run to settle before the scenario fails")
        sp.add_argument("--iso", type=int, default=30, help="requests per route in the statement pass (0 = skip)")
        sp.add_argument("--baseline", type=float, default=15, help="seconds of idle CPU baseline")

    v = sub.add_parser("viewers")
    v.add_argument("--n", type=int, default=10)
    v.add_argument("--active-runs", type=int, default=4)
    v.add_argument("--duration", type=float, default=120)
    v.add_argument("--flow", default="text6")
    frame(v)
    v.set_defaults(func=lambda a: asyncio.run(scenario(a, "A viewers", viewers_body)))
    b = sub.add_parser("runs")
    m = b.add_mutually_exclusive_group(required=True)
    m.add_argument("--concurrency", type=int, help="closed loop: C runs in flight")
    m.add_argument("--rate", type=float, help="open loop: R run creates per second")
    b.add_argument("--count", type=int, default=50)
    b.add_argument("--flow", default="text10")
    frame(b)
    b.set_defaults(func=lambda a: asyncio.run(scenario(a, "B runs", runs_body)))
    rp = sub.add_parser("report")
    rp.add_argument("out")
    rp.set_defaults(func=cmd_report)
    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
