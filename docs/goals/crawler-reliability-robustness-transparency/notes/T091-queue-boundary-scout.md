# T091 Queue Boundary Scout

## Summary

The first queue-boundary cleanup should not introduce a broad `WorkerAdapter` yet. The most reviewable first slice is to remove duplicated Redis slot Lua ownership from `CrawlService` and route optimistic slot acquire/release through the existing `LuaScripts` owner.

This is the right first move because it deletes a parallel implementation before adding a new seam. It also reduces typed-boundary evasions in a hot reliability path without changing ARQ queue behavior, pending queue behavior, watchdog recovery, or job lifecycle policy.

## Direct-Call Inventory

### Slot Acquire / Release

- `backend/src/intric/websites/domain/crawl_service.py:49-85` defines private `_acquire_slot_lua` and `_release_slot_lua` strings that duplicate `LuaScripts.ACQUIRE_SLOT` / `LuaScripts.RELEASE_SLOT`.
- `backend/src/intric/websites/domain/crawl_service.py:110-123` builds `tenant:{tenant_id}:active_jobs` and calls `redis_client.eval(...)` directly for optimistic acquire.
- `backend/src/intric/websites/domain/crawl_service.py:171-178` builds the same active slot key and calls `redis_client.eval(...)` directly for rollback release.
- `backend/src/intric/websites/domain/crawl_service.py:197-204` repeats the same direct release path for preempted jobs.
- `backend/src/intric/websites/domain/crawl_service.py:162` and `:216` duplicate the pre-acquired slot flag key string.
- `backend/src/intric/worker/redis/lua_scripts.py:35-88` is the existing canonical home for slot Lua scripts.
- `backend/src/intric/worker/redis/lua_scripts.py:170-177` already owns `slot_key(...)` and `preacquired_slot_key(...)`.
- `backend/src/intric/worker/crawl/slot_acquire.py` and `backend/src/intric/worker/crawl/slot_release.py` already reuse `LuaScripts` and have no `Any`, `cast`, or `getattr` evasions.

Canonical owner recommendation:

- Slot Lua source: `backend/src/intric/worker/redis/lua_scripts.py`.
- Slot Redis key formatting: `LuaScripts.slot_key(...)` and `LuaScripts.preacquired_slot_key(...)`.
- First Worker should make `CrawlService` call `LuaScripts.acquire_slot(...)` and `LuaScripts.release_slot(...)` instead of owning Lua strings or direct slot eval calls.

### Pending Queue

- `backend/src/intric/websites/domain/crawl_service.py:237-251` formats `tenant:{tenant_id}:crawl_pending`, serializes the job payload, and calls `rpush(...)` directly.
- `backend/src/intric/worker/feeder/queues.py:51` owns the same pending queue key in `PendingQueue._key(...)`.
- `backend/src/intric/worker/feeder/queues.py:141-146` owns `PendingQueue.add(...)` and already has deterministic serialization.
- `backend/src/intric/worker/crawl_feeder.py:186-189` owns dead-letter queue writes.
- `backend/src/intric/worker/crawl_feeder.py:357` scans `tenant:*:crawl_pending`.

Canonical owner recommendation:

- Pending queue key and queue operations should eventually be owned by `PendingQueue`.
- Do not include this in the first Worker because it touches queue enqueue failure semantics and job failure rollback behavior.

### ARQ Enqueue / Duplicate / Status

- `backend/src/intric/websites/domain/crawl_service.py:309-313` enqueues directly through `job_manager.enqueue(...)`.
- `backend/src/intric/worker/feeder/queues.py:220-226` wraps feeder enqueue and duplicate detection in `JobEnqueuer`.
- `backend/src/intric/worker/feeder/watchdog.py:787-817` imports ARQ `Job` / `JobStatus`, checks job status directly, and requeues through `job_manager.enqueue(...)`.

Canonical owner recommendation:

- ARQ job operations need a later dedicated boundary, but not before the Redis slot and queue ownership duplication is collapsed.
- The first Worker should not introduce `WorkerAdapter`; it would wrap duplicated Redis/Lua ownership instead of deleting it.

### Abort / Cancel / Worker Health / Watchdog Recovery

- Watchdog owns direct ARQ job status checks for requeue.
- Worker lifecycle state still leaks through `worker.py` and watchdog, with large `Any`/`cast` surfaces.
- These are broader reliability slices and should follow after slot Lua and pending queue canonical ownership are cleaner.

## Evasion Counts

Current `Any` / `cast(...)` / `getattr(...)` counts in the queue/Redis/slot boundary:

| File | Any | cast | getattr |
|---|---:|---:|---:|
| `backend/src/intric/websites/domain/crawl_service.py` | 0 | 4 | 0 |
| `backend/src/intric/worker/tenant_concurrency.py` | 0 | 0 | 4 |
| `backend/src/intric/worker/redis/lua_scripts.py` | 0 | 0 | 6 |
| `backend/src/intric/worker/feeder/watchdog.py` | 7 | 3 | 0 |
| `backend/src/intric/worker/feeder/queues.py` | 4 | 5 | 0 |
| `backend/src/intric/worker/crawl_feeder.py` | 4 | 2 | 0 |
| `backend/src/intric/worker/crawl/slot_acquire.py` | 0 | 0 | 0 |
| `backend/src/intric/worker/crawl/slot_release.py` | 0 | 0 | 0 |
| `backend/src/intric/worker/redis/client.py` | 2 | 0 | 0 |
| `backend/src/intric/worker/worker.py` | 21 | 5 | 2 |

The recommended first Worker should reduce `crawl_service.py` `cast(...)` count from 4 to 1 by deleting direct slot eval casts, while leaving the pending-queue `rpush(...)` cast for a later queue ownership slice.

## First Worker Recommendation

Objective:

Delete duplicated slot Lua ownership from `CrawlService` and route optimistic slot acquire/release through `LuaScripts`, preserving rollback and preemption behavior.

Allowed files:

- `backend/src/intric/websites/domain/crawl_service.py`
- `backend/tests/unittests/websites/test_crawl_service_slot_ownership.py`
- `docs/crawler-reliability-robustness-transparency-plan.md`
- `docs/goals/crawler-reliability-robustness-transparency/state.yaml`

Red test plan:

- Add behavior tests that fail today because `CrawlService` still sends private Lua strings and raw slot keys to Redis:
  - `release_job_resources(...)` must call Redis with `LuaScripts.RELEASE_SLOT`, `LuaScripts.slot_key(tenant_id)`, and delete `LuaScripts.preacquired_slot_key(job_id)`.
  - The `crawl(...)` enqueue-rollback path must delete `LuaScripts.preacquired_slot_key(job_id)` and release using `LuaScripts.RELEASE_SLOT` / `LuaScripts.slot_key(tenant_id)`.
- Add a supplemental architecture ownership regression that proves slot Lua constants live only in `LuaScripts`, and `CrawlService` does not own private slot Lua strings, `redis.call(...)` Lua bodies, direct private slot eval calls, or raw `tenant:*:active_jobs` / `slot_preacquired` literals.

Verification commands:

- `cd backend && uv run pytest tests/unittests/websites/test_crawl_service_slot_ownership.py -q`
- `cd backend && uv run ruff check src/intric/websites/domain/crawl_service.py tests/unittests/websites/test_crawl_service_slot_ownership.py`
- `cd backend && uv run ruff format --check src/intric/websites/domain/crawl_service.py tests/unittests/websites/test_crawl_service_slot_ownership.py`
- `cd backend && uv run pyright --project pyrightconfig.json src/intric/websites/domain/crawl_service.py tests/unittests/websites/test_crawl_service_slot_ownership.py`
- `! rg -n "_acquire_slot_lua|_release_slot_lua|redis_client\\.eval\\(self\\._.*slot_lua|redis\\.call\\(|tenant:.*active_jobs|job:[^\"]*slot_preacquired" backend/src/intric/websites/domain/crawl_service.py`

Stop conditions:

- Need to change ARQ enqueue behavior, duplicate handling, pending queue behavior, job failure rollback, or queue key format.
- Need to edit `tenant_concurrency.py`, `lua_scripts.py`, watchdog, feeder queues, worker runtime, or task manager.
- Need to introduce `WorkerAdapter` or any new interface/module.
- Need to stage unrelated `.devcontainer` changes.
- Verification fails twice for the same reason.

Comment cleanup:

- Delete the stale `FIX:` / previous-bug comments attached to the duplicated acquire Lua.
- Delete comments that say slot Lua is the same as `TenantConcurrencyLimiter`; that ownership moves to `LuaScripts`.
- Delete the direct-`redis_client.eval` explanatory comment in `release_job_resources(...)`; after the change the helper call name carries that meaning.

Non-goals:

- No pending queue ownership changes.
- No watchdog ARQ status cleanup.
- No `tenant_concurrency.py` `getattr(..., "ev" + "al")` cleanup yet.
- No `LuaScripts` eval typing cleanup yet.
- No admin/frontend work.
- No lifecycle, `CrawlAdminDetail`, `Phase` enum, or phase-duration work.
- No new files named helper, manager, processor, common, shared, or utils.

## Follow-Up Candidate Order

1. Collapse `CrawlService` slot Lua duplication into `LuaScripts`.
2. Move `CrawlService._add_to_pending_queue(...)` onto `PendingQueue.add(...)` with behavior tests for rpush failure and existing terminal failure rollback.
3. Replace `tenant_concurrency.py` direct script execution with `LuaScripts.acquire_slot(...)` / `release_slot(...)` if fallback semantics remain unchanged.
4. Centralize `LuaScripts` eval execution typing to remove the `getattr(redis, "ev" + "al")` evasions.
5. Only then reconsider a narrow ARQ `WorkerAdapter` around enqueue/status/abort/health.
