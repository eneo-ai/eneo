# T115 Queue Boundary Scout

## Problem

The crawler queue boundary still spreads the same ARQ crawl enqueue semantics across several owners:

- `worker/feeder/queues.py` parses pending queue JSON, builds `CrawlTask`, and calls `job_manager.enqueue(...)`.
- `websites/domain/crawl_service.py` builds `CrawlTask` again for direct manual handoff.
- `worker/feeder/watchdog.py` builds `CrawlTask` again for stuck-job requeue and also constructs `arq.jobs.Job` directly to inspect ARQ status.

This is more important than another one-file Redis typing cleanup. Redis `cast(Any, ...)` is noisy, but the reliability risk is duplicated job construction, duplicate ARQ status ownership, and tuple-shaped enqueue outcomes.

## Current Owners

| Concept | Current locations | Problem | Canonical home to move toward |
|---|---|---|---|
| ARQ crawl enqueue for an existing job row | `JobEnqueuer.enqueue`, `CrawlService._enqueue_to_arq`, `WatchdogService._requeue_job` | Same `CrawlTask` construction and `job_manager.enqueue(Task.CRAWL, ...)` semantics repeated | A concrete crawl enqueue owner under `worker/feeder`, not a broad `WorkerAdapter` yet |
| ARQ job status lookup | `watchdog._requeue_job`, `JobManager.get_job_status` | Watchdog duplicates `arq.jobs.Job(...)` construction even though `JobManager` already owns it | `JobManager.get_job_status` |
| Pending queue JSON payload | `CrawlPendingJobData`, `PendingQueue`, `JobEnqueuer.enqueue` | Serialization shape leaks into enqueue semantics as the primary API | Keep JSON parsing at the pending queue edge; delegate typed values to the enqueue owner |
| Redis list typing | `PendingQueue`, `CrawlFeeder`, `CapacityManager` | Multiple redis-py calls need casts under strict Pyright | Defer until one shared Redis protocol/boundary can serve all users |

## Verified Premises

- `JobManager.get_job_status(job_id)` already constructs `arq.jobs.Job(job_id=str(job_id), redis=self._redis)` and returns `await job.status()`.
- `build_arq_redis_settings(...)` and `build_redis_pool_kwargs(...)` both honor `settings.redis_db`, so ARQ status through `JobManager` and regular Redis worker state target the same Redis database.
- Production `CrawlTask(...)` constructors currently appear in `TaskService.queue_crawl`, `JobEnqueuer.enqueue`, `CrawlService._enqueue_to_arq`, and `WatchdogService._requeue_job`.
- `TaskService.queue_crawl` is job creation and remains out of scope for the next slice. The next slice should collapse only ARQ enqueue for already-created crawl jobs.

## Claude Gate

Claude rejected:

- A one-file `PendingQueue` Redis list protocol. It would reduce local casts but create a precedent for more narrow protocols instead of one shared Redis typing boundary.
- A new ARQ-status helper. `JobManager.get_job_status` already owns that behavior.
- A full `WorkerAdapter` now. It is still too broad and risks interface ceremony before the concrete owner is earned.

Claude recommended a refined concrete enqueue-owner slice:

- Introduce a typed crawl enqueue path for existing crawl jobs.
- Reuse it from pending queue feeder, manual direct enqueue, and watchdog requeue.
- Reuse `JobManager.get_job_status` from watchdog.
- Keep WorkerAdapter explicitly deferred.

Artifacts:

- `.codex/artifacts/claude-peer-loop-t115-queue-boundary-next-slice-scout-20260515T100427Z.md`

## Recommended Next Worker

### Objective

Create one concrete, typed owner for enqueueing already-created crawl jobs into ARQ, and reuse existing `JobManager.get_job_status(...)` for watchdog requeue status checks.

### Proposed Shape

- Keep the existing pending queue serialization shape (`CrawlPendingJobData`) at the Redis queue edge.
- Add a typed crawl enqueue request and outcome near `JobEnqueuer` or in a narrow `worker/feeder/crawl_enqueue.py`.
- Let `JobEnqueuer.enqueue_from_pending(...)` parse `CrawlPendingJobData` and delegate typed values to the new enqueue owner.
- Let `CrawlService._enqueue_to_arq(...)` and `WatchdogService._requeue_job(...)` use the same typed owner for already-created jobs.
- Let watchdog call `job_manager.get_job_status(...)` instead of constructing `arq.jobs.Job` directly.

### Red Tests

- Behavior test: typed crawl enqueue returns `ENQUEUED` when `job_manager.enqueue(...)` returns `True`.
- Behavior test: typed crawl enqueue returns `DUPLICATE` when `job_manager.enqueue(...)` returns `False`.
- Behavior test: typed crawl enqueue returns or raises the existing failure policy on exceptions without text-parsing duplicate errors.
- Behavior test: pending queue dict parsing delegates to the typed enqueue path and preserves invalid job-id handling.
- Behavior test: watchdog requeue uses `JobManager.get_job_status(...)` and the typed enqueue owner instead of constructing `arq.jobs.Job` directly.
- Source guard: `worker/feeder/watchdog.py` no longer imports `arq.jobs.Job`.

### Allowed Files

- `backend/src/intric/worker/feeder/queues.py`
- `backend/src/intric/worker/feeder/watchdog.py`
- `backend/src/intric/websites/domain/crawl_service.py`
- Optional narrow new file: `backend/src/intric/worker/feeder/crawl_enqueue.py`
- `backend/tests/unittests/worker/feeder/test_queues.py`
- `backend/tests/unittests/worker/feeder/test_watchdog_enqueue.py` or existing watchdog tests if present
- `backend/tests/unittests/websites/test_crawl_service_slot_ownership.py`
- `docs/crawler-reliability-robustness-transparency-plan.md`
- `docs/goals/crawler-reliability-robustness-transparency/state.yaml`

### Non-Goals

- No `WorkerAdapter` interface yet.
- No new protocol/factory/base class.
- No Redis list protocol cleanup in this slice.
- No slot acquire/release semantics changes.
- No pending queue key or JSON wire-shape changes.
- No terminal outcome changes.
- No admin or frontend changes.

### Stop Conditions

- If the slice requires changing pre-acquired slot rollback ordering.
- If `CrawlService` needs a different duplicate policy than the feeder/watchdog path and that policy is not already explicit.
- If the typed owner starts hiding terminal commits or slot release behavior.
- If implementation needs broad changes to `TaskService.queue_crawl` or generic non-crawl job enqueueing.
