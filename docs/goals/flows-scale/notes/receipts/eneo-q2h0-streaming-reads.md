# Inline streaming reads: measurement and validation receipt

**Cleanup correction on base `7766ca3a7`:** shared spool cleanup now preserves
the original exception or cancellation while attempting both close and unlink.
An otherwise standalone cleanup `OSError` becomes `ObjectContentUnavailableError`.
The resource measurements below predate this correction and remain unchanged;
the benchmark was not rerun for this cleanup-only change. Its focused regression
evidence is recorded under [Cleanup error precedence correction](#cleanup-error-precedence-correction).

**The revised RSS caps, growth comparison and unchanged latency gates passed.**
The benchmark completed all eight legs once: `1 passed in 61.89s (0:01:01)`.
The 384 MiB RSS growth was 2.484375 MiB ordinary and 3.187500 MiB local-path,
below their respective comparison limits of 7.937500 MiB and 5.875000 MiB.
The requested inline integration rerun passed: `35 passed in 98.23s (0:01:38)`.

The owner replaced the 1 MiB single-reader / 4 MiB aggregate caps with strictly
under **16 MiB per single reader** at every measured size and under **32 MiB
aggregate at N=4**. In each path mode, the 384 MiB RSS growth must also be
strictly below **twice the 16 MiB RSS growth plus 4 MiB**. Absolute latency
bounds are unchanged. These remain owner assumptions pending override.

The owner's rationale is that the previous caps omitted fixed driver, session
and spool overhead, while the measurements show growth that does not scale with
object size. The RSS measurements do not separately attribute those overheads;
the new comparison tests the stated growth criterion directly. Production code,
fixtures, chunk size and the completed full-suite baseline comparison stay
unchanged. Every previous threshold and measured result is retained below.

The preceding acquisition passed all absolute latency checks but failed five
RSS checks under the then-current caps. Both
64 MiB path modes now have single-read and N=4 measurements. Ordinary mode took
0.531061 s single and 0.678276 s p95; local-path mode took 0.439094 s single and
0.852130 s p95. The 64 MiB local-path single read grew RSS by 1.218750 MiB,
exceeding its 1 MiB cap; ordinary N=4 grew RSS by 4.984375 MiB, exceeding its
4 MiB cap. Three additional RSS failures occurred at 16/384 MiB. That run did
not meet those memory acceptance limits. The full integration run
reported 15 failures, all matching the pinned baseline by exact ID and failure
signature; there were no new or resolved integration failures.

The owner previously replaced the ratio gate with single 64 MiB reads under
2 seconds, nearest-rank
p95 at N=4 under 5 seconds, and 384 MiB reads under 60 seconds in both path
modes. The accompanying RSS limits were under four chunks (1 MiB) per reader
and under 16 chunks (4 MiB) for N=4; these are now superseded by the caps and
growth comparison above.

The owner reports that both ratio acquisitions ran while two other lanes ran
integration suites on the shared host. The concurrent p95 stayed near 2.24 s
while the single read improved from 0.967 s to 0.720 s, making the ratio fail
despite similar concurrent latency. The orchestrator will rerun the benchmark
alone on an idle host before landing. The current worker run retains all
measurements and does not claim that idle-host validation.

The previous acquisition was blocked by the revised 2.5× concurrency gate. It
measured **3.1100344623343434×**: ordinary-mode p95 was 2.2387589579448104 s
against a single read of 0.7198502090759575 s. It stopped before the 64 MiB
local-path leg and post-change full integration run. Memory allowances and both
384 MiB timing checks passed. Work stopped until the next owner ruling.

The original 2× gate failed: the 64 MiB ordinary single read took
0.9669113750569522 s, and four concurrent reads had nearest-rank p95
2.246710459003225 s, a ratio of **2.3235950232469764**. Work stopped at that
result. The owner then revised the assumption to **2.5×**, retaining the
384 MiB limit of **under 60 seconds**. The owner's rationale is that bounded
application memory is the objective and the observed slowdown represents I/O
contention on the shared PostgreSQL server. This receipt attributes that cause
to the owner; the measurements alone do not establish it.

The complete workload ran once under the preceding absolute bounds. Production code,
fixtures, chunk size and mode order remain unchanged. RSS assertions run
after acquisition of both path modes so a failed RSS bound cannot hide the
remaining local-path measurement. A failed latency bound still stops the run
immediately. Both failed ratio gates and all earlier acquisition results remain
below. No acquisition was retried to change its outcome.

Base: `7cb2872a0744d8fafcb2f069b9544fc4f660a78b`, worktree
`eneo-worker-q2h0`, 2026-09-21. This receipt describes an uncommitted candidate;
the orchestrator owns review and landing. Operator guidance remains in
[OBJECT_CONTENT.md](../../../../deployment/OBJECT_CONTENT.md).

## Frozen workload

Use the existing PostgreSQL 13 integration harness, its default pool of 20
connections plus 10 overflow, and the existing 262,144-byte inline chunk setting.
Fixture creation and conversion finish outside each isolated reader process.
Fixtures are deterministic incompressible bytes (`Random(42)`), at 16, 384, and
64 MiB in that order. Both ordinary incremental consumption and requested local
path consumption are measured. The local path is read incrementally as well.

At 64 MiB, each mode runs one isolated single read followed by one isolated batch
of four concurrent reads of the same object. The nearest-rank p95 of four samples
is their maximum. The original 2× and subsequent 2.5× ratio assumptions are
retired; ratios remain reported as measurements. Acceptance now requires the
64 MiB single read to finish in under 2 seconds and its N=4 p95 in under
5 seconds, in each path mode. Each 384 MiB read must finish in under 60 seconds.
These are
small-sample harness gates, not production latency forecasts. No timing retry or
chunk-row fallback is authorized after a frozen latency failure.

The measurement harness lives in
`backend/tests/integration/object_content/test_inline_streaming_benchmark.py`
and `inline_streaming_reader.py`. It captures successful slice queries separately
from all SQL statements. Total statements also include the transaction BEGIN
and ROLLBACK reported by SQLAlchemy's transaction events. Driver connection
initialization and the premeasurement pool warmup are outside those totals.

Application RSS is sampled every 2 ms in the isolated reader, using macOS
`proc_pidinfo` (or `/proc/self/statm` on Linux). The process high-water RSS is
reported separately. Current RSS acceptance is strictly under 16 MiB for each
single reader and under 32 MiB for four concurrent readers, measured after
imports, mapper initialization and pool warmup. Each path mode separately checks
that the 384 MiB delta is below twice its 16 MiB delta plus 4 MiB. Earlier limits
were 32 chunks (8 MiB) per reader, followed by four chunks (1 MiB) per reader
and 16 chunks (4 MiB) aggregate; all results against those limits remain below.
PostgreSQL backend VmRSS/VmHWM comes from the container's `/proc/<pid>/status`;
these values include shared-buffer mappings and are not private allocator usage.
The observer samples lock waits separately. PostgreSQL execution time and buffer
accesses are measured with EXPLAIN ANALYZE BUFFERS for every substring projection.
The exceptional whole-payload SHA-256 fence is measured separately; it is not
chunk-bounded and does not appear in successful-read metadata.

The owner reports concurrent integration suites from two other lanes during
the ratio runs. No other validation from this slice ran during resource
acquisition.

## Initial cold-reader result and measurement correction

The first 16 MiB ordinary read performed 64 successful slice queries, 66 SQL
statements and two transaction boundaries (68 total). It took
0.8233213748317212 seconds. Baseline RSS was 335,872,000 bytes; peak and process
high-water RSS were both 347,602,944 bytes, a delta of 11,730,944 bytes
(44.75 chunks). This failed the unchanged 8 MiB read allowance:

```text
1 failed in 77.19s (0:01:17)
```

A separate initialization probe, without reading payload bytes, measured:
336,789,504 bytes before `configure_mappers()`, 347,422,720 afterward, and
347,504,640 after compiling a metadata SELECT. Mapper initialization alone cost
10,633,216 bytes (10.14 MiB). The initial reader had warmed raw SQL connections
but had not initialized the ORM. The subsequent acquisition explicitly runs
`configure_mappers()` during startup. Production code, chunk size, the 8 MiB
allowance and both latency thresholds were unchanged at that point. The cold-reader
result above is retained rather than presented as a passing measurement.

The first PostgreSQL 16 MiB projection leg took 9.039 ms in aggregate and
2,443 shared-buffer accesses. The separate full-payload fence hash took
18.078 ms and 2,128 buffer accesses. Its reader backend grew from 15,790,080
bytes RSS to 39,792,640 bytes RSS (40,087,552 high-water).

## Fixture-construction correction

The initialized-reader acquisition measured the two 16 MiB modes successfully:
ordinary 0.4826214590575546 seconds and 704,512 bytes RSS growth; local path
0.4953473750501871 seconds and 1,064,960 bytes RSS growth. Both performed 64
slice queries and 68 total statements, with no observed lock waits.
It then failed outside reader measurement while constructing the 384 MiB
fixture: `Random.randbytes` exceeded Python's single `getrandbits` size bound.
The run reported `1 failed in 83.12s (0:01:23)`.

Fixture generation now concatenates deterministic 4 MiB random blocks. This
changes no production file or acceptance limit. Both acquisition failures are
retained here; neither was a frozen latency failure.

## Original acquisition and required stop at 2×

Command, from the worktree root:

```sh
ENEO_RUN_INLINE_READ_BENCHMARK=1 PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run --no-sync --directory backend pytest tests/integration/object_content/test_inline_streaming_benchmark.py -q -s
```

The original acquisition, after the two documented harness corrections, reported:

```text
E                   AssertionError: Frozen concurrent-read latency threshold failed; stop this slice
E                   assert 2.3235950232469764 <= 2
1 failed in 131.31s (0:02:11)
```

No fixture construction, mapper initialization or connection warmup is included
in read latency or RSS deltas. Peak sampled RSS equalled the process high-water
RSS in every completed leg. All completed legs observed zero database lock waits.

| MiB | Mode | N | Per-read latency / p95 (s) | Slice queries | Total statements | Peak RSS (MiB) | RSS delta (MiB) | Delta / chunk |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | ordinary | 1 | 0.332986 | 64 | 68 | 333.531250 | 0.640625 | 2.5625 |
| 16 | local path | 1 | 0.367481 | 64 | 68 | 329.468750 | 1.125000 | 4.5000 |
| 384 | ordinary | 1 | 6.884172 | 1536 | 1540 | 330.234375 | 2.515625 | 10.0625 |
| 384 | local path | 1 | 6.936853 | 1536 | 1540 | 331.953125 | 3.421875 | 13.6875 |
| 64 | ordinary | 1 | 0.966911 | 256 | 260 | 334.015625 | 1.546875 | 6.1875 |
| 64 | ordinary | 4 | 2.246710 | 1024 | 1040 | 333.359375 | 5.593750 | 22.3750 |

The four concurrent latencies were 2.246710459003225, 2.2277233339846134,
2.2241884579416364 and 2.236925208941102 seconds. The allowed p95 was
1.9338227501139044 seconds. The aggregate RSS delta for all four readers was
5,865,472 bytes; the 64 MiB single-read delta was 1,622,016 bytes (6.1875 chunks),
below the unchanged allowance of 8,388,608 bytes (32 chunks). Both 384 MiB modes
passed the 60-second absolute threshold.

The candidate keeps 256 KiB as the existing chunk value. It performs 1,536 slice
queries and 1,540 total statements for 384 MiB; this is the measured round-trip
cost of bounded projections. The failed concurrency ratio prevented accepting
that tradeoff under the original 2× assumption. It is below the revised 2.5×
gate. No alternate chunk value was tried.

| MiB | Sum of slice execution (ms) | Slice buffer accesses | Exceptional whole-hash execution (ms) | Whole-hash buffer accesses |
| ---: | ---: | ---: | ---: | ---: |
| 16 | 3.039 | 2443 | 11.547 | 2128 |
| 384 | 526.572 | 60200 | 886.558 | 50990 |
| 64 | 27.729 | 10032 | 77.734 | 8502 |

Backend resident memory is separate from application memory. The table below
reports the reader backends, not the process that built the fixtures or ran the
EXPLAIN probes. PostgreSQL RSS includes shared-buffer mappings, so these values
do not establish a chunk bound on PostgreSQL resident memory.

| MiB | Mode | N | Backend RSS before (MiB) | Backend RSS after (MiB) | Backend high-water (MiB) |
| ---: | --- | ---: | --- | --- | --- |
| 16 | ordinary | 1 | 15.086 | 37.945 | 38.320 |
| 16 | local path | 1 | 15.074 | 37.871 | 38.340 |
| 384 | ordinary | 1 | 14.359 | 144.266 | 144.402 |
| 384 | local path | 1 | 14.527 | 144.211 | 144.277 |
| 64 | ordinary | 1 | 14.621 | 139.586 | 139.867 |
| 64 | ordinary | 4 | 14.473, 14.430, 14.469, 14.574 | 139.398, 139.352, 139.402, 139.406 | 139.840, 139.668, 139.781, 139.852 |

The original acquisition did not reach the local-path 64 MiB single/concurrent
legs because the ordinary mode crossed the then-mandatory stop threshold first.
The production source hashes below identify that stopped candidate and remain
frozen for the resumed validation.

## Resumed acquisition and required stop at 2.5×

The owner authorized replacing only the concurrency assumption, from 2× to
2.5×, after the original 2.3235950232469764× result. The benchmark assertion then
used 2.5. No production source, fixture, chunk size, memory allowance or other
gate changed. The same benchmark command above ran once and reported:

```text
E                   AssertionError: Frozen concurrent-read latency threshold failed; stop this slice
E                   assert 3.1100344623343434 <= 2.5
FAILED tests/integration/object_content/test_inline_streaming_benchmark.py::test_frozen_inline_read_resource_gate
1 failed in 85.35s (0:01:25)
```

| MiB | Mode | N | Per-read latency / p95 (s) | Slice queries | Total statements | Peak RSS (MiB) | RSS delta (MiB) | Delta / chunk |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | ordinary | 1 | 0.192549 | 64 | 68 | 329.468750 | 1.453125 | 5.8125 |
| 16 | local path | 1 | 0.149454 | 64 | 68 | 329.671875 | 1.406250 | 5.6250 |
| 384 | ordinary | 1 | 3.908280 | 1536 | 1540 | 331.375000 | 1.546875 | 6.1875 |
| 384 | local path | 1 | 3.385804 | 1536 | 1540 | 331.546875 | 2.343750 | 9.3750 |
| 64 | ordinary | 1 | 0.719850 | 256 | 260 | 330.765625 | 0.812500 | 3.2500 |
| 64 | ordinary | 4 | 2.238759 | 1024 | 1040 | 334.531250 | 5.281250 | 21.1250 |

The concurrent latencies were 2.21583087509498, 2.230845290934667,
2.2358081249985844 and 2.2387589579448104 seconds. The revised allowed p95 was
1.7996255226898938 seconds. The 64 MiB ordinary single-read RSS delta was
851,968 bytes (3.25 chunks), below the unchanged 8,388,608-byte allowance
(32 chunks). Four readers grew aggregate RSS by 5,537,792 bytes (21.125 chunks),
below their unchanged 33,554,432-byte allowance. Pool capacity remained 20 plus
10 overflow. All completed legs observed zero lock waits, and sampled peak RSS
equalled process high-water RSS.

The concurrent p95 was close to the original result (2.246710459003225 s), while
the measured single-read latency was lower. Both measurements are retained;
neither permits disregarding the revised ratio failure. The local-path 64 MiB
leg was not reached. There was no retry, chunk-size tuning or fallback.

| MiB | Sum of slice execution (ms) | Slice buffer accesses | Exceptional whole-hash execution (ms) | Whole-hash buffer accesses |
| ---: | ---: | ---: | ---: | ---: |
| 16 | 5.833 | 2443 | 10.456 | 2128 |
| 384 | 297.014 | 60200 | 372.862 | 50990 |
| 64 | 40.012 | 10032 | 84.649 | 8502 |

| MiB | Mode | N | Backend RSS before (MiB) | Backend RSS after (MiB) | Backend high-water (MiB) |
| ---: | --- | ---: | --- | --- | --- |
| 16 | ordinary | 1 | 15.062 | 37.926 | 38.438 |
| 16 | local path | 1 | 15.051 | 37.852 | 38.250 |
| 384 | ordinary | 1 | 14.332 | 144.246 | 144.348 |
| 384 | local path | 1 | 14.395 | 144.195 | 144.480 |
| 64 | ordinary | 1 | 14.539 | 139.926 | 140.371 |
| 64 | ordinary | 4 | 14.484, 14.465, 14.480, 14.609 | 139.754, 139.723, 139.746, 139.773 | 140.051, 140.098, 140.184, 140.098 |

The PostgreSQL RSS caveat above also applies here. The exceptional fence hash
remains whole-payload database work, separate from successful slice reads.

## Resumed validation commands

Before either edit in this iteration, `ls` confirmed both object-content test
directories, both pytest collections completed, the real audio launcher ran,
and Pyright and Ruff checks completed. Pytest uses the absolute candidate
`PYTHONPATH` below because the shared virtual environment can point its editable
installation at another worktree.

From `backend`, unless the command supplies `--directory backend`:

| Command / selection | Observed result |
| --- | --- |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content --collect-only -q` | `326/327 tests collected (1 deselected) in 1.93s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content --collect-only -q` | `192 tests collected in 12.71s` |
| `/Users/ccimen/.claude/skills/eneo-slice-landing/scripts/lanetest.sh /Users/ccimen/eneo/eneo-worker-q2h0 tests/unittests/flows/test_audio_spool.py` | `13 passed in 13.32s` |
| `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| `uv run ruff check` on all ten changed Python files, before and after the gate edit | `All checks passed!` |
| `uv run ruff format --check` on all ten changed Python files, before and after the gate edit | `10 files already formatted` |
| Resource benchmark command above, revised 2.5× gate | `1 failed in 85.35s (0:01:25)`; exit 1 |
| `git diff --check` | Exit 0; no whitespace errors |

The benchmark log is `/tmp/smxs-2-it2-measurement.log`; preflight logs are
`/tmp/smxs-2-it2-preflight-integration.log`,
`/tmp/smxs-2-it2-preflight-unit.log`, `/tmp/smxs-2-it2-pyright.log` and
`/tmp/lanetest-eneo-worker-q2h0-180548.log`. The post-change full integration run
and a new full unit execution were not started after the mandatory stop. The
earlier focused passing executions remain recorded below. The opt-in benchmark
failure is not covered by the 15-ID baseline allowlist.

## Acquisition under absolute latency and tightened RSS bounds

The benchmark command above completed all eight legs once. All latency, SQL
count and observed lock-wait checks passed. RSS checks were evaluated together
after acquisition, retaining the failure for every mode that exceeded its cap.
The run reported:

```text
FAILED tests/integration/object_content/test_inline_streaming_benchmark.py::test_frozen_inline_read_resource_gate
1 failed in 155.97s (0:02:35)
```

The strict RSS limit is 1,048,576 bytes for each isolated single reader and
4,194,304 bytes for the isolated four-reader process. The table reports aggregate
RSS growth for N=4, not four separately sampled process values.

| MiB | Mode | N | Per-read latency / p95 (s) | Slice queries | Total statements | Peak RSS (MiB) | RSS delta (MiB) | Delta / chunk | RSS gate |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 16 | ordinary | 1 | 0.209634 | 64 | 68 | 330.093750 | 0.671875 | 2.6875 | pass |
| 16 | local path | 1 | 0.255479 | 64 | 68 | 330.437500 | 3.109375 | 12.4375 | FAIL |
| 384 | ordinary | 1 | 10.079622 | 1536 | 1540 | 330.578125 | 1.734375 | 6.9375 | FAIL |
| 384 | local path | 1 | 10.550811 | 1536 | 1540 | 332.046875 | 4.078125 | 16.3125 | FAIL |
| 64 | ordinary | 1 | 0.531061 | 256 | 260 | 330.890625 | 0.937500 | 3.7500 | pass |
| 64 | ordinary | 4 | 0.678276 | 1024 | 1040 | 333.265625 | 4.984375 | 19.9375 | FAIL |
| 64 | local path | 1 | 0.439094 | 256 | 260 | 329.671875 | 1.218750 | 4.8750 | FAIL |
| 64 | local path | 4 | 0.852130 | 1024 | 1040 | 324.984375 | 1.640625 | 6.5625 | pass |

The exact failing RSS deltas were 3,260,416 bytes (16 MiB local path),
1,818,624 bytes (384 MiB ordinary), 4,276,224 bytes (384 MiB local path),
5,226,496 bytes (64 MiB ordinary N=4) and 1,277,952 bytes (64 MiB local path).
These measurements do not satisfy the new caps. There was no implementation,
chunk-size or fixture change to address them.

Ordinary N=4 latencies were 0.6599967919755727, 0.6782755840104073,
0.654526290949434 and 0.6514102909713984 seconds. Local-path N=4 latencies were
0.7843747499864548, 0.8521295411046594, 0.8220020420849323 and
0.7740038330666721 seconds. The reported ratios were 1.2772087269705867 and
1.9406536635382405 respectively; neither ratio is an acceptance assertion now.
Every completed leg observed zero lock waits, and sampled peak RSS equalled
process high-water RSS. Pool capacity remained 20 plus 10 overflow.

| MiB | Sum of slice execution (ms) | Slice buffer accesses | Exceptional whole-hash execution (ms) | Whole-hash buffer accesses |
| ---: | ---: | ---: | ---: | ---: |
| 16 | 4.077 | 2443 | 20.688 | 2128 |
| 384 | 1392.779 | 60200 | 1363.584 | 50990 |
| 64 | 213.462 | 10032 | 257.969 | 8502 |

| MiB | Mode | N | Backend RSS before (MiB) | Backend RSS after (MiB) | Backend high-water (MiB) |
| ---: | --- | ---: | --- | --- | --- |
| 16 | ordinary | 1 | 15.066 | 37.957 | 38.359 |
| 16 | local path | 1 | 15.055 | 37.883 | 38.281 |
| 384 | ordinary | 1 | 14.352 | 144.242 | 144.480 |
| 384 | local path | 1 | 14.414 | 144.168 | 144.473 |
| 64 | ordinary | 1 | 14.609 | 139.531 | 140.035 |
| 64 | ordinary | 4 | 16.117, 16.215, 16.113, 16.117 | 139.617, 139.707, 139.602, 139.609 | 139.934, 139.863, 139.980, 139.926 |
| 64 | local path | 1 | 14.762 | 139.395 | 139.777 |
| 64 | local path | 4 | 14.637, 14.641, 14.762, 14.641 | 139.328, 139.352, 139.395, 139.320 | 139.652, 139.863, 139.902, 139.762 |

The PostgreSQL RSS values include shared-buffer mappings. The exceptional hash
remains whole-payload work in PostgreSQL, separate from the successful-read
metadata and substring projections. These figures make no claim that PostgreSQL
resident memory is bounded by one chunk.

Raw evidence is in `/tmp/smxs-2-it3-measurement.log`. The orchestrator's isolated
idle-host run remains a required prelanding step; it was not performed here.

## Validation under the absolute bounds

Preflight preceded either edit in this iteration. Both test directories were
listed first. Commands ran from `backend` unless they specify otherwise.

| Command / selection | Observed result |
| --- | --- |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content --collect-only -q` | `326/327 tests collected (1 deselected) in 0.28s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content --collect-only -q` | `192 tests collected in 4.10s` |
| `/Users/ccimen/.claude/skills/eneo-slice-landing/scripts/lanetest.sh /Users/ccimen/eneo/eneo-worker-q2h0 tests/unittests/flows/test_audio_spool.py` | `13 passed in 1.97s`; `pytest exit: 0` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content -q` | `192 passed in 9.54s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content -q -n 4` | `15 failed, 309 passed, 2 skipped in 369.33s (0:06:09)`; exit 1 |
| `uv run pyright`, before and after the test edit | `0 errors, 0 warnings, 0 informations` |
| `uv run ruff check` on exactly the ten changed Python files, before and after the test edit | `All checks passed!` |
| `uv run ruff format --check` on those files, before and after the test edit | `10 files already formatted` |
| Resource benchmark command above, absolute bounds | `1 failed in 155.97s (0:02:35)`; exit 1 |
| `git diff --check` | Exit 0; no whitespace errors |

The full integration command is
`PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content -q -n 4`.
It uses the repository CI's four-worker mode, with separate test containers per
worker. Benchmark acquisition finished before the full integration, unit or
final type-check runs began. All 15 failing IDs match the baseline list below;
their normalized exception messages also match, including the before-publication
cancellation timeout. Exact ID differences: added `[]`, resolved `[]`. Changed
failure signatures: `[]`. There are 35 additional passing integration cases
relative to the pinned baseline. The opt-in benchmark is skipped in the ordinary
suite; its separately executed RSS failure is not covered by the baseline
allowlist.

Logs use `/tmp/smxs-2-it3-`: `preflight-integration.log`, `preflight-unit.log`,
`unit.log`, `integration.log`, `pyright.log`, `pyright-final.log` and
`measurement.log`. The audio launcher wrote
`/tmp/lanetest-eneo-worker-q2h0-181620.log`.

## Acquisition under the 16 MiB / 32 MiB RSS caps and growth comparison

The same benchmark command ran once under the revised memory acceptance:

```text
1 passed in 61.89s (0:01:01)
```

All single-reader RSS deltas were below 16 MiB, all N=4 deltas were below 32 MiB,
and both path modes passed the object-size comparison. Latency, query counts
and observed lock waits also passed without changing their assertions.

| MiB | Mode | N | Per-read latency / p95 (s) | Slice queries | Total statements | Sampled peak RSS (MiB) | Process high-water RSS (MiB) | RSS delta (MiB) | Delta / chunk |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | ordinary | 1 | 0.145142 | 64 | 68 | 328.953125 | 328.953125 | 1.968750 | 7.8750 |
| 16 | local path | 1 | 0.138347 | 64 | 68 | 328.312500 | 328.312500 | 0.937500 | 3.7500 |
| 384 | ordinary | 1 | 2.943413 | 1536 | 1540 | 331.468750 | 331.468750 | 2.484375 | 9.9375 |
| 384 | local path | 1 | 2.860475 | 1536 | 1540 | 330.234375 | 330.234375 | 3.187500 | 12.7500 |
| 64 | ordinary | 1 | 0.384163 | 256 | 260 | 331.218750 | 331.218750 | 0.687500 | 2.7500 |
| 64 | ordinary | 4 | 0.594817 | 1024 | 1040 | 333.515625 | 333.531250 | 5.484375 | 21.9375 |
| 64 | local path | 1 | 0.446027 | 256 | 260 | 331.828125 | 331.843750 | 1.437500 | 5.7500 |
| 64 | local path | 4 | 0.574379 | 1024 | 1040 | 331.984375 | 331.984375 | 4.703125 | 18.8125 |

The strict object-size comparisons, calculated in bytes, were:

- Ordinary: `2,605,056 < 2 * 2,064,384 + 4,194,304 = 8,323,072`.
- Local path: `3,342,336 < 2 * 983,040 + 4,194,304 = 6,160,384`.

Ordinary N=4 latencies were 0.5948171669151634, 0.5760933749843389,
0.5890068328008056 and 0.5703419160563499 seconds. Local-path N=4 latencies
were 0.553246625000611, 0.5743787500541657, 0.5596312920097262 and
0.5555219170637429 seconds. The descriptive ratios were 1.5483456334599985 and
1.2877672541647804; neither was used as an acceptance assertion.

Every leg observed zero lock waits. Pool capacity remained 20 plus 10 overflow.
For the 64 MiB ordinary N=4 and local-path single-reader legs, process
high-water RSS exceeded the 2 ms sampled peak by 16,384 bytes. Using those
high-water readings yields RSS growth of 5.500000 MiB and 1.453125 MiB,
respectively, also within their caps. The receipt extraction initially asserted
that sampled peaks equalled high-water readings, as in earlier acquisitions;
that diagnostic assertion failed. Both distinct readings are retained above.
No benchmark assertion or measurement was changed to address that difference.

| MiB | Sum of slice execution (ms) | Slice buffer accesses | Exceptional whole-hash execution (ms) | Whole-hash buffer accesses |
| ---: | ---: | ---: | ---: | ---: |
| 16 | 5.285 | 2443 | 9.110 | 2128 |
| 384 | 210.522 | 60200 | 268.479 | 50990 |
| 64 | 15.763 | 10032 | 37.481 | 8502 |

| MiB | Mode | N | Backend RSS before (MiB) | Backend RSS after (MiB) | Backend high-water (MiB) |
| ---: | --- | ---: | --- | --- | --- |
| 16 | ordinary | 1 | 15.062 | 37.953 | 38.355 |
| 16 | local path | 1 | 15.051 | 37.879 | 38.262 |
| 384 | ordinary | 1 | 14.336 | 144.238 | 144.453 |
| 384 | local path | 1 | 14.406 | 144.164 | 144.488 |
| 64 | ordinary | 1 | 14.527 | 139.766 | 140.148 |
| 64 | ordinary | 4 | 14.504, 14.508, 14.504, 14.633 | 139.652, 139.656, 139.652, 139.703 | 140.039, 139.930, 140.039, 139.965 |
| 64 | local path | 1 | 14.633 | 139.703 | 140.086 |
| 64 | local path | 4 | 14.504, 14.625, 14.508, 14.496 | 139.652, 139.691, 139.656, 139.645 | 140.039, 140.016, 140.047, 140.098 |

The PostgreSQL memory caveat remains unchanged: these readings include shared
buffers, and exceptional failure fencing hashes the complete payload in
PostgreSQL. Neither is described as chunk-bounded.

## Validation under the revised RSS caps

Preflight preceded both edits. Commands ran from `backend` unless they specify
otherwise. The production source hashes below still match the measured candidate.

| Command / selection | Observed result |
| --- | --- |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content/test_inline_streaming_benchmark.py --collect-only -q` | `1 test collected in 0.10s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content/test_inline_streaming.py --collect-only -q` | `35 tests collected in 0.10s` |
| Resource benchmark command above, revised RSS caps and growth comparison | `1 passed in 61.89s (0:01:01)`; exit 0 |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content/test_inline_streaming.py -q` | `35 passed in 98.23s (0:01:38)`; exit 0 |
| `uv run pyright`, preflight and final | `0 errors, 0 warnings, 0 informations` |
| `uv run ruff check` on exactly the ten changed Python files, preflight and final | `All checks passed!` |
| `uv run ruff format --check` on those files, preflight and final | `10 files already formatted` |
| Read-only receipt extraction | Initial `AssertionError` from assuming sampled peak equalled process high-water; distinct readings recorded above |
| `git diff --check` | Exit 0; no whitespace errors |

Both requested modules passed. The completed full-suite comparison is retained
without rerunning it: added failing IDs `[]`, resolved IDs `[]`, changed
failure signatures `[]`. Its exact 15-ID allowlist and the prior unit/audio
results remain below. The orchestrator's planned idle-host run before landing
remains separate from this worker's passing acquisition.

Raw evidence uses `/tmp/smxs-2-it4-`: `preflight-benchmark.log`,
`preflight-inline.log`, `measurement.log`, `inline.log`,
`pyright-preflight.log` and `pyright-final.log`.

## Commands and retained logs from the original implementation

All plain `uv run` commands below ran from `backend`, unless `--directory backend`
is present. Preflight preceded the first source or test edit.

| Command / selection | Observed result |
| --- | --- |
| `uv run pytest tests/integration/object_content --collect-only -q` | `290/291 tests collected (1 deselected) in 0.95s` |
| `uv run pytest tests/unittests/object_content --collect-only -q` | `186 tests collected in 7.15s` |
| `uv run pytest tests/unittests/flows/test_audio_spool.py --collect-only -q` | `13 tests collected in 1.68s` |
| Env-file / PYTHONPATH audio launcher form with `--collect-only -q` | `tests/unittests/flows/test_audio_spool.py: 13` |
| `uv run pytest tests/integration/object_content -q` (baseline) | `15 failed, 274 passed, 1 skipped, 1 deselected in 1576.30s (0:26:16)` |
| `uv run pytest tests/unittests/object_content -q` (baseline) | `186 passed in 10.31s` |
| `uv run pytest tests/unittests/flows/test_audio_spool.py -q` | `13 passed in 2.32s` |
| Env-file / PYTHONPATH audio launcher form | `13 passed in 3.30s` |
| `uv run pytest tests/integration/object_content/test_inline_streaming.py -q -x` | First `1 failed in 28.94s`; then `4 passed in 45.64s` |
| `uv run pytest tests/unittests/object_content/test_s3_integrity.py -q -k 'closes_without or pending_s3 or local_verified'` | `6 failed, 33 deselected in 0.64s` |
| `uv run pytest tests/unittests/object_content -q` (intermediate) | `1 failed, 191 passed in 11.52s` (wrapped-stream assertion); then `1 failed, 191 passed in 80.99s (0:01:20)` (new detached-close red test) |
| `uv run pytest tests/integration/object_content/test_inline_streaming.py -q -k 'corruption'` | First `5 failed, 5 passed, 4 deselected in 57.82s`; then `10 passed, 19 deselected in 158.81s (0:02:38)` |
| `uv run pytest tests/integration/object_content/test_inline_streaming.py -q -k 'not corruption'` | `1 failed, 18 passed, 10 deselected in 190.76s (0:03:10)` (invalid failed-state fixture, subsequently corrected) |
| `uv run pytest tests/unittests/object_content/test_content_read_lifecycle.py -q` | `1 failed, 3 passed in 0.99s` before cleanup settlement |
| `uv run pytest tests/unittests/object_content tests/integration/object_content/test_inline_streaming.py -q` | `221 passed in 210.02s (0:03:30)` |
| `PYTHONPATH=src uv run --directory backend pytest tests/integration/object_content/test_inline_streaming.py -q -k 'empty_inline or short_slice or 500_unique or ready_inline_range'` | `6 passed, 29 deselected in 86.66s (0:01:26)` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run --directory backend pytest tests/unittests/object_content/test_s3_integrity.py tests/unittests/object_content/test_content_read_lifecycle.py -q` | `43 passed in 1.15s` |
| `/Users/ccimen/.claude/skills/eneo-slice-landing/scripts/lanetest.sh /Users/ccimen/eneo/eneo-worker-q2h0 tests/unittests/flows/test_audio_spool.py` | `13 passed in 8.96s`; `pytest exit: 0` |
| `uv run pyright` | Baseline and final: `0 errors, 0 warnings, 0 informations`; intermediate runs each exposed one strict typing error, both corrected |
| `uv run ruff check` / `uv run ruff format --check` on all ten changed Python files | `All checks passed!`; `10 files already formatted` |
| The same Ruff commands on each subsequently corrected benchmark helper | `All checks passed!`; `1 file already formatted` |
| Resource benchmark command above, first acquisition | `1 failed in 77.19s (0:01:17)` (cold mapper initialization included) |
| Same benchmark, initialized reader | `1 failed in 83.12s (0:01:23)` (384 MiB fixture constructor overflow) |
| Same benchmark, block-built fixtures | `1 failed in 131.31s (0:02:11)` (mandatory concurrency gate; stopped) |
| `git diff --check` | No whitespace errors |

Raw local evidence is retained in `/tmp/smxs-2-streaming-*.log`, including
`baseline-integration`, `focused`, `edge-contracts`, `final-read-units`,
`measurement`, `measurement-initialized` and `measurement-block-fixtures`.
The audio script wrote `/tmp/lanetest-eneo-worker-q2h0-174005.log`.
These local logs are not a substitute for the counts and measurements preserved
in this tracked receipt.

## Cleanup error precedence correction

The review finding was reproduced with a real `BufferedRandom` wrapping a
`FileIO` whose writes fail. A buffered write succeeds without reaching the raw
file; seek flushes and raises the typed unavailable error, then close attempts
the same failing flush. Before correction, the second raw `OSError` replaced
the typed error. Cancelling a task with buffered bytes similarly escaped as
`OSError` instead of leaving the task cancelled.

Six tests were written and run before editing the production owner. They cover
the repeated buffered flush failure, actual task cancellation with buffered
bytes, standalone close failure, and unlink failure with no primary error,
an unavailable error or cancellation. The first run reported:

```text
6 failed in 0.21s
```

Cleanup now captures close and unlink failures separately, always attempting
both operations. An active primary exception resumes unchanged after cleanup;
without one, a cleanup `OSError` is normalized to unavailable. Cancellation
during close retains the existing settlement behavior. The focused rerun was:

```text
6 passed in 0.44s
```

The buffered tests assert the raw file is closed and its path removed. The
unlink-denied cases assert an unlink attempt and preservation of the original
exception, or normalization when there was none; the test removes the denied
path during its own teardown. A failed filesystem unlink is not reported as a
successful deletion.

The source change is confined to `verified_spool.py`; the new test owner is
`backend/tests/unittests/object_content/test_verified_spool.py`. The corrected
spool source SHA-256 is
`c45ac2ef5802f971cbae3ac8407413a5609659fe91b68a28ed4a79a3102a6a22`.
The other four production files retain their measured hashes below. This
correction has no new resource measurement or full-suite baseline comparison.

Preflight preceded both test and implementation edits. The shared-spool unit
module was new, so the existing object-content unit directory was collected
before creating it. Commands ran from `backend` unless they specify otherwise:

| Command / selection | Observed result |
| --- | --- |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content/test_s3_integrity.py --collect-only -q` | `39 tests collected in 0.03s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content --collect-only -q` | `192 tests collected in 3.07s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content/test_inline_streaming.py --collect-only -q` | `35 tests collected in 0.11s` |
| `/Users/ccimen/.claude/skills/eneo-slice-landing/scripts/lanetest.sh /Users/ccimen/eneo/eneo-worker-q2h0 tests/unittests/flows/test_audio_spool.py` | `13 passed in 1.56s`; `pytest exit: 0` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content/test_verified_spool.py -q` | Red: `6 failed in 0.21s`; green: `6 passed in 0.44s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/unittests/object_content/test_s3_integrity.py tests/unittests/object_content/test_verified_spool.py -q` | `45 passed in 1.06s` |
| `PYTHONPATH=/Users/ccimen/eneo/eneo-worker-q2h0/backend/src uv run pytest tests/integration/object_content/test_inline_streaming.py -q` | `35 passed in 111.05s (0:01:51)` |
| `uv run pyright`, preflight and final | `0 errors, 0 warnings, 0 informations` |
| `uv run ruff check src/eneo/object_content/verified_spool.py tests/unittests/object_content/test_verified_spool.py` | `All checks passed!` |
| `uv run ruff format --check src/eneo/object_content/verified_spool.py tests/unittests/object_content/test_verified_spool.py` | `2 files already formatted` |

The real PostgreSQL inline module passed. Logs are retained as
`/tmp/smxs-2-it5-*.log`; the audio launcher log is
`/tmp/lanetest-eneo-worker-q2h0-185606.log`. No git command was run for this
correction.

## Measured source identity before the cleanup correction

The five production files were frozen before acquisition:

| File | SHA-256 |
| --- | --- |
| `backend/src/eneo/object_content/content_repository.py` | `6ec963c14403a5c0b4f87f88b3ba2efc5a8e07156cae9780fa1a2a9baf0f39f5` |
| `backend/src/eneo/object_content/content_service.py` | `64bdf28e68d3d7a69804ae4c0988f7a18c7f29b619a3dd1a8c96e21e08fa7a1d` |
| `backend/src/eneo/object_content/inline_content_store.py` | `56a4777a51f47e1cea2d0d430636b26dcd56016a381569be1aefc4486d4fbeec` |
| `backend/src/eneo/object_content/s3_object_store.py` | `ab8a03c344e0c1d8f1148e86822ccee084377d664175959c7bd84ad7e5efc17f` |
| `backend/src/eneo/object_content/verified_spool.py` | `25ee3ee4c592137aaf3771cc13035ad0d174a5eafc8654bb3cdf758298c06d7c` |

## Test-first evidence

The first real PostgreSQL projection test failed with zero slice queries where
nine were required (`1 failed in 28.94s`). Its four fresh/converted and ordinary/
local-path combinations then passed (`4 passed in 45.64s`). Six S3 cancellation,
unconsumed-body and local-I/O tests failed before the extraction
(`6 failed, 33 deselected in 0.64s`). The unconsumed-body assertion was corrected
to inspect the underlying stream, since StreamingBody's inherited `closed`
property does not report its wrapped stream's state.

The complete-observation tests exposed missing SHA-256 forwarding on the
not-ready branch (`5 failed, 5 passed, 4 deselected in 57.82s`); after forwarding,
the same selection reported `10 passed, 19 deselected in 158.81s (0:02:38)`.
The stronger detached-close cancellation contract failed first
(`1 failed, 3 passed in 0.99s`) and now settles cleanup before raising cancellation.

The focused unit and inline integration run reported:

```text
221 passed in 210.02s (0:03:30)
```

The additional empty-payload, short-slice, 501-grant batching and range tests:

```text
6 passed, 29 deselected in 86.66s (0:01:26)
```

After the final S3 range ownership adjustment:

```text
43 passed in 1.15s
```

The canonical audio launcher reported:

```text
13 passed in 8.96s
pytest exit: 0
```

Pyright reported `0 errors, 0 warnings, 0 informations`. Ruff check passed and
format checking reported `10 files already formatted` before the initialization
adjustment; checking that one changed benchmark helper again also passed.
`git diff --check` passed. A failed authorization fixture initially omitted the
required failure code; the corrected fixture passes without weakening a product
constraint.

## Baseline failure allowlist

The canonical Beads board's `eneo-oa5o` comment 1049, dated 2026-09-21 17:03,
provided the allowlist. The worktree's copied Beads snapshot lacked that comment;
it was read from `/Users/ccimen/eneo/flows-tidy-ai-builder` without changing the
board. On the pinned, unedited implementation base, the full integration run
reported:

```text
15 failed, 274 passed, 1 skipped, 1 deselected in 1576.30s (0:26:16)
```

Exact failures:

```text
tests/integration/object_content/test_file_icon_adoption.py::test_file_capture_persists_payload_above_the_old_inline_default
tests/integration/object_content/test_file_icon_adoption.py::test_signed_download_preserves_the_established_text_and_image_variants
tests/integration/object_content/test_file_icon_adoption.py::test_text_hydration_without_readable_text_returns_typed_not_found
tests/integration/object_content/test_file_icon_legacy_fallback.py::test_file_and_icon_legacy_fallbacks_execute_against_postgres
tests/integration/object_content/test_file_storage_lifecycle.py::test_remote_failure_publishes_no_multi_content_family_rows[1]
tests/integration/object_content/test_file_storage_lifecycle.py::test_remote_failure_publishes_no_multi_content_family_rows[2]
tests/integration/object_content/test_file_storage_lifecycle.py::test_remote_failure_publishes_no_multi_content_family_rows[3]
tests/integration/object_content/test_file_storage_lifecycle.py::test_cancellation_before_publication_leaves_no_file_family_rows
tests/integration/object_content/test_file_storage_lifecycle.py::test_database_rollback_after_verified_uploads_publishes_no_family_rows
tests/integration/object_content/test_file_storage_lifecycle.py::test_cancellation_after_final_promotion_preserves_the_visible_family
tests/integration/object_content/test_file_storage_lifecycle.py::test_inline_and_object_store_save_the_same_exact_bytes
tests/integration/object_content/test_file_storage_lifecycle.py::test_generated_file_family_content_uses_operator_not_source_business_limit
tests/integration/object_content/test_inventory_usage.py::test_inventory_groups_each_content_once_by_product_owner
tests/integration/object_content/test_inventory_usage.py::test_inventory_query_stays_bounded_for_thousands_without_loading_payloads
tests/integration/object_content/test_moves.py::test_admin_command_requires_readiness_before_queueing
```

The File/Icon and file-family upload doubles reject the `pdf_limits` argument;
the before-publication cancellation test times out on that same failed setup.
The legacy fallback passes an unsupported `expected_tenant_id`; the two
inventory fixtures pass an invalid `Files.user_id`; the admin move test uses a
stale deployment-policy revision. Matching an ID alone does not exempt a different
failure in the candidate.

## Preserved callers and contracts

Before editing, `get_readable_sources` was called by `open_content` and
`read_content_bytes`, both in `content_service.py`. After editing, only the
not-ready download branch and the intentional batch branch call it.

Production callers of `read_content_bytes` remain `files/file_service.py:1151`
and `files/file_content_loader.py:259`. Existing test calls remain in
`test_inline_content_service.py:116` and `test_content_service.py:550,697`;
additional wrappers call the original method in the assistant/app fleet HTTP
contract tests. Batch materialization retains conflict rejection and one source
query per page of at most 500 unique grants. A new 501-grant test observes exactly
two source queries; the existing remote batch test is unchanged.

Ready inline metadata validates ID, tenant, access class and AVAILABLE state,
and distinguishes physical length from canonical length. Every physical byte is
hashed before a length/hash mismatch can be fenced. A missing payload remains a
typed state error. An unexpectedly short SQL slice is unavailable: it exposes no
bytes and supplies no incomplete digest to the durable corruption fence. Empty
canonical content verifies with zero slice queries. Reads before conversion
readiness retain the whole-payload behavior.

FileDownload, the audio spool, StorageKind, deployment policy, the move queue and
slice-1 conversion are unchanged. Audio path adoption is tested without consuming
download chunks. No schema, settings, generated contracts, git state or history
were changed.
