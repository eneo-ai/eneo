"""Crawl Feeder Service - Pull-based queueing to prevent burst overload.

Why: When schedulers trigger, they may queue dozens of websites simultaneously.
This overwhelms per-tenant concurrency limits, causing retry storms and queue congestion.

How: Feeder observes existing TenantConcurrencyLimiter state and meters enqueue rate:
- Scheduler adds jobs to pending Redis list (not directly to ARQ)
- Feeder checks active_jobs count every 10s
- Enqueues to ARQ only when capacity exists (active < max_concurrent)
- Worker uses existing limiter.acquire/release (unchanged)

Result: Smooth, predictable enqueue rate instead of burst spikes.
Reuses existing concurrency infrastructure, no parallel permit system needed.
"""

import asyncio
import hashlib
import json
from uuid import UUID
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

from intric.main.config import get_settings
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.main.container.container import Container

logger = get_logger(__name__)


def _generate_deterministic_job_id(run_id: UUID, url: str) -> str:
    """Generate deterministic job ID for idempotent enqueueing.

    Why: Prevents duplicate jobs if feeder crashes and restarts.
    ARQ will reject duplicate job_ids, making enqueue idempotent.

    Args:
        run_id: Crawl run UUID (unique per crawl)
        url: Website URL (for additional uniqueness)

    Returns:
        Deterministic job ID string

    Example:
        run_id="a1b2c3..." url="https://example.com"
        -> "crawl:a1b2c3...:5d41402a"
    """
    # Use MD5 hash of URL for compact, deterministic identifier
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"crawl:{run_id}:{url_hash}"


class CrawlFeeder:
    """Meters crawl job enqueue rate based on available concurrency capacity.

    Why: Prevents burst overload by only enqueueing when capacity exists.
    Observes the existing TenantConcurrencyLimiter state (active_jobs counter).
    """

    def __init__(self, container: "Container"):
        self.container = container
        self.settings = get_settings()
        self._running = False

    async def _try_acquire_leader_lock(
        self, redis_client: aioredis.Redis
    ) -> bool:
        """Try to acquire leader lock for feeder singleton.

        Why: Ensures only ONE feeder runs even with multiple worker processes.
        Uses Redis SET NX with TTL for automatic failover if leader crashes.

        Returns:
            True if lock acquired (this instance is leader), False otherwise
        """
        import socket

        key = "crawl_feeder:leader"
        ttl = 30  # Lock expires after 30 seconds for automatic failover
        worker_id = socket.gethostname()

        try:
            # Atomic SET with NX (only if not exists) and EX (expiry)
            # Why: If another feeder holds the lock, this returns False
            acquired = await redis_client.set(key, worker_id, nx=True, ex=ttl)
            return bool(acquired)
        except Exception as exc:
            logger.warning(
                "Failed to acquire feeder leader lock",
                extra={"error": str(exc)},
            )
            return False

    async def _refresh_leader_lock(
        self, redis_client: aioredis.Redis
    ) -> None:
        """Refresh leader lock TTL while running.

        Why: Keeps lock alive while we're the active leader.
        """
        key = "crawl_feeder:leader"
        try:
            await redis_client.expire(key, 30)
        except Exception:
            pass  # Silent failure, next acquire attempt will handle it

    # Lua script for atomic slot acquisition (same logic as TenantConcurrencyLimiter)
    _acquire_slot_lua: str = (
        "local key = KEYS[1]\n"
        "local limit = tonumber(ARGV[1])\n"
        "local ttl = tonumber(ARGV[2])\n"
        "if limit <= 0 then\n"
        "  return 1\n"
        "end\n"
        "local current = redis.call('INCR', key)\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "if current > limit then\n"
        "  local after_decr = redis.call('DECR', key)\n"
        "  if after_decr <= 0 then\n"
        "    redis.call('DEL', key)\n"
        "  else\n"
        "    redis.call('EXPIRE', key, ttl)\n"
        "  end\n"
        "  return 0\n"
        "end\n"
        "return current\n"
    )

    async def _try_acquire_slot(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> bool:
        """Atomically try to acquire a concurrency slot for this tenant.

        Why: Eliminates race condition between feeder capacity check and worker acquire.
        Uses same Lua script as TenantConcurrencyLimiter for atomic INCR-then-check.

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection

        Returns:
            True if slot acquired, False if at capacity
        """
        key = f"tenant:{tenant_id}:active_jobs"
        max_concurrent = self.settings.tenant_worker_concurrency_limit
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            result = await redis_client.eval(
                self._acquire_slot_lua,
                1,
                key,
                str(max_concurrent),
                str(ttl),
            )

            if isinstance(result, bytes):
                result = int(result)

            acquired = bool(result and int(result) > 0)

            if not acquired:
                logger.debug(
                    "Feeder slot acquisition failed (at capacity)",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": max_concurrent,
                    },
                )

            return acquired

        except Exception as exc:
            logger.warning(
                "Failed to acquire slot in feeder",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return False

    async def _mark_slot_preacquired(
        self, job_id: UUID, redis_client: aioredis.Redis
    ) -> None:
        """Mark that the feeder pre-acquired a slot for this job.

        Why: Worker checks this flag to skip limiter.acquire() (slot already held).
        TTL ensures cleanup if job is never picked up.
        """
        key = f"job:{job_id}:slot_preacquired"
        try:
            # TTL matches semaphore TTL - if job isn't picked up by then, slot will expire anyway
            await redis_client.set(key, "1", ex=self.settings.tenant_worker_semaphore_ttl_seconds)
        except Exception as exc:
            logger.warning(
                "Failed to mark slot as preacquired",
                extra={"job_id": str(job_id), "error": str(exc)},
            )

    async def _release_slot(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> None:
        """Release a previously acquired slot (used when ARQ enqueue fails).

        Why: If feeder acquires slot but fails to enqueue, must release to prevent leak.
        """
        key = f"tenant:{tenant_id}:active_jobs"
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            # Lua script for safe decrement (same as TenantConcurrencyLimiter release)
            release_lua = (
                "local key = KEYS[1]\n"
                "local ttl = tonumber(ARGV[1])\n"
                "local current = redis.call('GET', key)\n"
                "if not current then\n"
                "  return 0\n"
                "end\n"
                "current = redis.call('DECR', key)\n"
                "if not current or current <= 0 then\n"
                "  redis.call('DEL', key)\n"
                "  return 0\n"
                "end\n"
                "redis.call('EXPIRE', key, ttl)\n"
                "return current\n"
            )
            await redis_client.eval(release_lua, 1, key, str(ttl))
        except Exception as exc:
            logger.warning(
                "Failed to release slot in feeder",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def _get_available_capacity(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> int:
        """Check available crawl capacity for this tenant (read-only).

        Why: Used to decide how many pending jobs to consider.
        Actual slot acquisition is done atomically per-job via _try_acquire_slot().

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection

        Returns:
            Number of jobs that can be enqueued (0 if at capacity)
        """
        # Use same Redis key as TenantConcurrencyLimiter
        # Why: Ensures feeder and worker coordinate on same state
        key = f"tenant:{tenant_id}:active_jobs"

        try:
            active_jobs_bytes = await redis_client.get(key)
            max_concurrent = self.settings.tenant_worker_concurrency_limit

            # Allow capacity check even if key doesn't exist (will be 0 active)
            # Why: _try_acquire_slot() handles actual atomic acquisition
            if not active_jobs_bytes:
                return max_concurrent  # No active jobs, full capacity available

            # Decode bytes to int, with safety clamping
            # Why: Prevents crashes and ensures value is within valid range
            active_jobs = int(active_jobs_bytes.decode())
            active_jobs = max(0, min(active_jobs, max_concurrent))

            # Calculate available capacity
            available = max_concurrent - active_jobs
            return max(0, available)

        except Exception as exc:
            logger.warning(
                "Failed to check available capacity",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            # Conservative: assume no capacity
            return 0

    async def _get_pending_crawls(
        self, tenant_id: UUID, redis_client: aioredis.Redis, limit: int
    ) -> list[dict]:
        """Get pending crawl jobs from the queue.

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection
            limit: Maximum number of jobs to retrieve

        Returns:
            List of job data dictionaries
        """
        key = f"tenant:{tenant_id}:crawl_pending"

        try:
            # Get first N items from list (FIFO queue)
            pending_bytes = await redis_client.lrange(key, 0, limit - 1)

            if not pending_bytes:
                return []

            # Parse JSON job data
            pending_jobs = []
            for job_bytes in pending_bytes:
                try:
                    job_data = json.loads(job_bytes.decode())
                    pending_jobs.append(job_data)
                except json.JSONDecodeError as parse_exc:
                    logger.warning(
                        "Failed to parse pending job",
                        extra={"tenant_id": str(tenant_id), "error": str(parse_exc)},
                    )
                    continue

            return pending_jobs

        except Exception as exc:
            logger.warning(
                "Failed to get pending crawls",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return []

    async def _enqueue_crawl_job(
        self, job_data: dict, tenant_id: UUID
    ) -> tuple[bool, UUID]:
        """Enqueue a crawl job to ARQ using pre-created job record.

        Why: Job and CrawlRun records already created by scheduler.
        Feeder only handles ARQ enqueueing with deterministic job_id for idempotency.

        Args:
            job_data: Job parameters from pending queue (includes job_id from DB)
            tenant_id: Tenant identifier

        Returns:
            Tuple of (success: bool, job_id: UUID)
        """
        # Parse job_id early to avoid re-parsing in exception handler
        # Why: If this fails, we want a clean error, not a masked one
        try:
            job_id = UUID(job_data["job_id"])
        except (KeyError, ValueError, TypeError) as exc:
            logger.error(
                "Invalid job_id in pending job data",
                extra={"tenant_id": str(tenant_id), "job_data": job_data, "error": str(exc)},
            )
            # Return a nil UUID to indicate failure - caller should handle
            return False, UUID("00000000-0000-0000-0000-000000000000")

        try:
            from intric.websites.crawl_dependencies.crawl_models import CrawlTask, CrawlType
            from intric.jobs.job_models import Task

            # Reconstruct CrawlTask parameters
            params = CrawlTask(
                user_id=UUID(job_data["user_id"]),
                website_id=UUID(job_data["website_id"]),
                run_id=UUID(job_data["run_id"]),
                url=job_data["url"],
                download_files=job_data["download_files"],
                crawl_type=CrawlType(job_data["crawl_type"]),
            )

            # Enqueue to ARQ with deterministic job_id
            # Why: If feeder crashes and retries, ARQ rejects duplicate IDs
            job_manager = self.container.job_manager()
            await job_manager.enqueue(
                task=Task.CRAWL,
                job_id=job_id,  # Use pre-created ID for idempotency
                params=params,
            )

            logger.debug(
                "Enqueued crawl job from feeder",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "website_id": job_data["website_id"],
                    "url": job_data["url"],
                },
            )
            return True, job_id

        except Exception as exc:
            # Handle "job already exists" as success for idempotency
            # Why: If feeder crashes after enqueue but before LREM, job stays in pending.
            # On retry, ARQ returns "already exists" error. We treat this as SUCCESS
            # so LREM proceeds and clears the job from pending (prevents infinite loop).

            error_msg = str(exc).lower()

            # Check for duplicate job error - use specific patterns to avoid false positives
            # Why: Broad matching like "job_id" could match "invalid job_id" validation errors
            is_duplicate = (
                "already exists" in error_msg
                or "duplicate" in error_msg
                or "job exists" in error_msg
            )

            if is_duplicate:
                logger.info(
                    "Job already in ARQ queue (idempotent), treating as success",
                    extra={
                        "tenant_id": str(tenant_id),
                        "job_id": str(job_id),
                        "url": job_data.get("url"),
                        "reason": "duplicate_job_id",
                    },
                )
                # Return TRUE so LREM proceeds and removes from pending
                return True, job_id

            # Real error - return false, job stays in pending for retry
            logger.error(
                "Failed to enqueue crawl job from feeder",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_data": job_data,
                    "error": str(exc),
                },
            )
            return False, job_id

    async def _remove_from_pending(
        self, tenant_id: UUID, job_data: dict, redis_client: aioredis.Redis
    ) -> None:
        """Remove job from pending queue after successful enqueue.

        Args:
            tenant_id: Tenant identifier
            job_data: Job data to remove
            redis_client: Redis connection
        """
        key = f"tenant:{tenant_id}:crawl_pending"

        try:
            # Remove first occurrence (LREM count=1)
            # Why: Preserves FIFO order for remaining jobs
            job_json = json.dumps(job_data, default=str, sort_keys=True)
            await redis_client.lrem(key, 1, job_json)
        except Exception as exc:
            logger.warning(
                "Failed to remove from pending queue",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def _process_tenant_queue(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> None:
        """Process pending crawls for one tenant.

        Why: Atomically acquires slots and enqueues jobs when capacity exists.
        FIX: Eliminates race condition by acquiring slot BEFORE enqueueing.

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection
        """
        # Check available capacity (read-only hint for batch sizing)
        available = await self._get_available_capacity(tenant_id, redis_client)

        if available <= 0:
            return  # No capacity, skip this tenant

        # Get pending jobs (limit to available capacity and batch size)
        # Why: Batch size prevents enqueueing too many at once
        limit = min(available, self.settings.crawl_feeder_batch_size)
        pending_jobs = await self._get_pending_crawls(tenant_id, redis_client, limit)

        if not pending_jobs:
            return  # No pending jobs for this tenant

        logger.info(
            f"Processing {len(pending_jobs)} pending crawls",
            extra={
                "tenant_id": str(tenant_id),
                "available_capacity": available,
                "pending_count": len(pending_jobs),
            },
        )

        # Enqueue each pending job with atomic slot acquisition
        enqueued_count = 0
        failed_count = 0
        skipped_capacity = 0

        for job_data in pending_jobs:
            # Extract job_id early for flag operations
            # Why: Need job_id before enqueue to mark flag first
            try:
                job_id = UUID(job_data["job_id"])
            except (KeyError, ValueError, TypeError):
                logger.warning(
                    "Invalid job_id in pending job, skipping",
                    extra={"tenant_id": str(tenant_id), "job_data": job_data},
                )
                failed_count += 1
                continue

            # FIX: Atomically acquire slot BEFORE enqueueing
            # Why: Eliminates race condition between feeder GET and worker INCR
            slot_acquired = await self._try_acquire_slot(tenant_id, redis_client)

            if not slot_acquired:
                # At capacity - stop processing this tenant
                # Remaining jobs stay in pending queue for next cycle
                skipped_capacity = len(pending_jobs) - enqueued_count - failed_count
                logger.debug(
                    "Stopping tenant processing: at capacity",
                    extra={
                        "tenant_id": str(tenant_id),
                        "enqueued": enqueued_count,
                        "skipped": skipped_capacity,
                    },
                )
                break

            # FIX: Mark flag BEFORE enqueueing (safe hand-off)
            # Why: If enqueue succeeds but mark fails, worker would double-acquire
            # By marking first, we ensure flag exists before job enters ARQ queue
            await self._mark_slot_preacquired(job_id, redis_client)

            # Now enqueue to ARQ
            success, returned_job_id = await self._enqueue_crawl_job(job_data, tenant_id)

            if success:
                # Remove from pending queue
                await self._remove_from_pending(tenant_id, job_data, redis_client)
                enqueued_count += 1
            else:
                # Enqueue failed - rollback: delete flag and release slot
                # Why: Prevents slot leak and stale flag when ARQ enqueue fails
                try:
                    await redis_client.delete(f"job:{job_id}:slot_preacquired")
                except Exception:
                    pass  # Best effort cleanup
                await self._release_slot(tenant_id, redis_client)
                failed_count += 1

        if enqueued_count > 0 or failed_count > 0 or skipped_capacity > 0:
            logger.info(
                f"Feeder cycle complete: {enqueued_count} enqueued, {failed_count} failed, {skipped_capacity} skipped (capacity)",
                extra={"tenant_id": str(tenant_id)},
            )

    async def run_forever(self) -> None:
        """Run the feeder loop with leader election.

        Why: Only ONE feeder runs across all worker processes using Redis leader lock.
        This prevents N workers from spawning N feeders (which would recreate burst problem).

        Leader Lock Pattern:
        - Each worker tries to acquire lock on startup
        - Only one succeeds (becomes leader)
        - Others sleep and retry (become leader if current leader crashes)
        - Lock TTL=30s for automatic failover
        """
        if not self.settings.crawl_feeder_enabled:
            logger.info("Crawl feeder disabled, not starting")
            return

        logger.info(
            "Starting crawl feeder service with leader election",
            extra={
                "interval_seconds": self.settings.crawl_feeder_interval_seconds,
                "batch_size": self.settings.crawl_feeder_batch_size,
            },
        )
        self._running = True

        try:
            redis_client = self.container.redis_client()
        except Exception as exc:
            logger.error(f"Failed to get Redis client: {exc}")
            return

        while self._running:
            try:
                # CRITICAL: Try to become leader
                # Why: Prevents multiple feeders from running simultaneously
                if not await self._try_acquire_leader_lock(redis_client):
                    # Not leader, sleep and retry
                    # Why: Another worker is already running the feeder
                    await asyncio.sleep(5)
                    continue

                # We are the leader, run one feeder cycle
                logger.debug("Feeder leader lock acquired, processing queues")

                # Find all tenants with pending crawls
                # Why: Use SCAN instead of KEYS for production safety
                pattern = "tenant:*:crawl_pending"
                tenant_ids = set()

                cursor = 0
                while True:
                    cursor, keys = await redis_client.scan(
                        cursor=cursor, match=pattern, count=100
                    )

                    for key_bytes in keys:
                        key = key_bytes.decode()
                        # Extract tenant_id from key: tenant:{uuid}:crawl_pending
                        parts = key.split(":")
                        if len(parts) >= 2:
                            try:
                                tenant_ids.add(UUID(parts[1]))
                            except ValueError:
                                continue

                    if cursor == 0:
                        break

                # Process each tenant's pending queue
                # Why: Single feeder processes ALL tenants efficiently
                for tenant_id in tenant_ids:
                    try:
                        await self._process_tenant_queue(tenant_id, redis_client)
                    except Exception as exc:
                        logger.error(
                            f"Error processing tenant queue: {exc}",
                            extra={"tenant_id": str(tenant_id)},
                        )
                        continue  # Don't let one tenant's error stop others

                # Refresh leader lock before sleeping
                # Why: Keeps us as leader for next cycle
                await self._refresh_leader_lock(redis_client)

                # Sleep until next cycle
                await asyncio.sleep(self.settings.crawl_feeder_interval_seconds)

            except Exception as exc:
                logger.error(f"Error in feeder loop: {exc}")
                # Continue running even on errors
                # Why: Feeder should be resilient, not crash the worker
                await asyncio.sleep(self.settings.crawl_feeder_interval_seconds)

    async def stop(self) -> None:
        """Stop the feeder loop gracefully."""
        logger.info("Stopping crawl feeder service")
        self._running = False
