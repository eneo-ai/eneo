# File/Icon bridge qualification on PostgreSQL 13

The disposable PostgreSQL 13 rehearsal passed the released-schema upgrade,
worker process death and recovery, concurrent product reads/uploads, and backup
restore checks. It found and fixed a preflight compatibility defect: published
`v2.1.1` predates `files.parent_file_id`, so the preflight must select the source
query from the applied migration history instead of requiring that column.

This is local correctness and capacity evidence. It does not qualify an
unspecified production dataset, traffic level, recovery budget, replica topology,
or external object-store backup procedure. Those deployment gates remain in
`ocs-51g.6` and the [release contract](FILE_ICON_RELEASE_CONTRACT.md).

## Frozen profile

The source is `v2.1.1` commit
`527c49ec48029f80845e8672694d6e58ecd78220`: its 354 historical Alembic revisions
resolve to one head, `3eb6a34b6733`. The candidate starts from develop
`07a89aaa8808953b7e571b7f68d5cbc8079770e8`, includes the preflight fix, and upgrades
to bridge schema `202609071000`.

The pinned `pgvector/pgvector:pg13` image digest is recorded in the
[machine-readable result](evidence/file-icon-bridge-pg13.json). Its disposable
Docker container has 2 CPUs and 2 GiB memory. PostgreSQL uses the Docker Desktop
Linux filesystem, without replicas or replication slots. The worker runs as a
separate native Python 3.11.14 process on an arm64 development host with 14
physical CPUs and 48 GiB RAM. This shared host is not a production latency model.

The capacity fixture contains 277 files and one icon, producing 281 legacy
variants and 226,693,178 logical bytes (216.19 MiB). It includes 256 small binary
images, Unicode extracted text and transcription, original bytes, three empty
variants, eight compressible 1 MiB images, eight deterministic incompressible
1 MiB images, and one 200 MiB image. The large value repeats the deterministic
1 MiB random block; its PostgreSQL copy still exercises a full large TOAST value.

The worker uses 32 rows and the default 128 MiB estimated batch bound. Its
recovery lease is 300 seconds; the intentionally killed worker uses 2 seconds.
The harness invokes the real `run_once` with 50 ms gaps to keep the rehearsal
bounded. It does not measure production minute-cron elapsed time. File routes
use API-key authentication and signed downloads; Icon reads use the public
route. Traffic concurrency is one, through the real application and ASGI
transport, without a reverse proxy or external model calls.

Before the capacity run, the acceptance gates were zero byte/reference
mismatches, zero failed API requests, completion within 300 seconds, worker
maximum RSS at most 512 MiB, and database-volume free space at least 512 MiB.
The database container additionally enforces its 2 GiB memory limit. These are
fixture gates, not recommended production budgets.

## Recorded result

| Measurement                                                     |                         Result |
| --------------------------------------------------------------- | -----------------------------: |
| Preflight                                                       |                         0.44 s |
| Expand and inventory from released head                         |                         1.93 s |
| Adoption active work / elapsed loop time                        |       8.56 s / 9.07 s, 11 runs |
| Worker maximum RSS / total process CPU                          | 413.84 MiB / 11.62 CPU seconds |
| Foreground API p50 / p95 / p99                                  |               57 / 87 / 146 ms |
| Timed API operations / failures                                 |                        273 / 0 |
| PostgreSQL sampled RSS peak                                     |                   1,269.51 MiB |
| PostgreSQL container memory peak, including cache               |                   1,999.90 MiB |
| PostgreSQL container CPU over the full rehearsal                |              93.39 CPU seconds |
| Original database relation size peak                            |                     450.97 MiB |
| Generated WAL over the full rehearsal                           |                   1,142.24 MiB |
| Sampled retained WAL peak                                       |                        464 MiB |
| Minimum free database-volume space                              |                     362.09 GiB |
| Temporary query bytes / two backup files                        |                 0 / 712.47 MiB |
| Restore both backups / start application on restored bridge     |               29.23 s / 0.79 s |
| Full rehearsal, including fixture construction and verification |                       134.49 s |

The resource sampler covered source creation, upgrades, worker activity, dumps,
restores, and verification; generated WAL and CPU therefore are not adoption-only
costs. It captured 68 samples with a nominal 0.5-second interval plus collection
time. Sampled peaks can miss shorter transients. The database memory result is
close to the container limit; the much smaller worker RSS does not establish
database memory headroom. The large-value SQL verification and fixture seeding
also contribute to that peak.

The process-death test kills the worker while its payload insert is blocked and
uncommitted. PostgreSQL rolls back that insert; the durable lease remains and
the restarted worker completes without duplicates. Every inventoried variant
has its exact surviving reference, available content, and matching payload
size/digest. All frozen source columns are unchanged, including text originals,
transcriptions, empty values, and icons. Both pre-upgrade and adopted backups
restore; the application starts on the adopted restore and serves sampled old
files, the icon, and every new upload from the traffic loop.

No S3 endpoint is configured in this profile. Remote endpoint conformance,
placement moves, and early-selection recovery remain separate integration tests.
A real deployment with remote authority still needs a matched database and
object-store restore. There are no replica lag/catch-up results because this
fixture has no replica. The 200 MiB value is verified in PostgreSQL; the timed
API sample is small-file traffic, not a 200 MiB network-download benchmark.

## Reproduce

From `backend/`, with Docker available and the frozen Python dependencies
installed:

```bash
uv sync --frozen --all-groups
ENEO_FILE_ICON_REHEARSAL_PROFILE=capacity \
ENEO_FILE_ICON_REHEARSAL_OUTPUT=/tmp/file-icon-bridge-pg13.json \
uv run pytest -q -m migration_isolation \
  tests/integration/migrations/test_file_icon_bridge_rehearsal.py
```

Omit the profile variable for a small smoke fixture. Run this isolated module in
its own pytest invocation: it intentionally starts at the released schema and
restores separate databases instead of using the ordinary test cleanup. All
containers, databases, and worker processes belong to this fixture and are
removed on completion. The output contains metadata and measurements, not
payloads or connection credentials.

For a later contraction rehearsal, set `ENEO_FILE_ICON_REHEARSAL_BACKUP` to a new
local file path. After all checks pass, the fixture exports its synthetic adopted
PostgreSQL backup there. An existing file is never overwritten. Restore that
backup in a separate disposable database using the contraction candidate; this
tests the handoff between the actual bridge worker and the later application.

The focused preflight regression is in
`tests/integration/migrations/test_file_icon_preflight.py`. Existing
`test_file_icon_inline_backfill.py` and `test_file_icon_migration_controls.py`
cover oversize rejection before payload production, corrected target selection,
pause/restart, failure recovery, concurrency, and bounded scheduling. Preserve
the bridge candidate and this evidence when the later release retires the
temporary runtime and its tests.
