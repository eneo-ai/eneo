"""Crawl Service - Handles individual crawl requests with optimistic slot acquisition.

Implements "Optimistic Acquire" pattern for manual/bulk crawls:
- Try to acquire concurrency slot immediately
- If acquired: Direct to ARQ with pre-acquired flag (low latency)
- If at capacity: Add to pending queue for feeder (no retry storm)

This eliminates retry storms for manual crawls while maintaining low latency
for normal operations when capacity is available.
"""

import json
from typing import TYPE_CHECKING
from uuid import UUID

import redis.asyncio as aioredis

from intric.jobs.job_manager import job_manager
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.websites.domain.crawl_run import CrawlRun

if TYPE_CHECKING:
    from intric.jobs.task_service import TaskService
    from intric.websites.domain.crawl_run_repo import CrawlRunRepository
    from intric.websites.domain.website import Website

logger = get_logger(__name__)


class CrawlService:
    """Handles crawl requests with optimistic concurrency slot acquisition.

    When crawl feeder is enabled, uses optimistic acquire pattern:
    1. Create job record in DB
    2. Try to atomically acquire concurrency slot
    3. If acquired: enqueue directly to ARQ with pre-acquired flag
    4. If at capacity: add to pending queue for feeder to process later

    This provides low latency when capacity exists, and graceful queueing
    when at capacity (instead of retry storms).
    """

    # Lua script for atomic slot acquisition (same as TenantConcurrencyLimiter)
    # FIX: Only refresh TTL on SUCCESS path - prevents zombie counters when acquire fails
    # Bug: Previous version refreshed TTL on both success AND failure, keeping counter alive forever
    _acquire_slot_lua: str = (
        "local key = KEYS[1]\n"
        "local limit = tonumber(ARGV[1])\n"
        "local ttl = tonumber(ARGV[2])\n"
        "if limit <= 0 then\n"
        "  return 1\n"
        "end\n"
        "local current = redis.call('INCR', key)\n"
        "if current > limit then\n"
        "  local after_decr = redis.call('DECR', key)\n"
        "  if after_decr <= 0 then\n"
        "    redis.call('DEL', key)\n"
        "  end\n"
        "  -- DO NOT refresh TTL on failure - let counter expire naturally if unused\n"
        "  return 0\n"
        "end\n"
        "-- Success: refresh TTL only after confirming slot acquired\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    )

    # Lua script for safe slot release (same as TenantConcurrencyLimiter)
    _release_slot_lua: str = (
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

    def __init__(
        self,
        repo: "CrawlRunRepository",
        task_service: "TaskService",
        redis_client: aioredis.Redis,
    ):
        self.repo = repo
        self.task_service = task_service
        self.redis_client = redis_client
        self.settings = get_settings()

    async def _try_acquire_slot(self, tenant_id: UUID) -> bool:
        """Atomically try to acquire a concurrency slot for this tenant.

        Uses same Lua script as TenantConcurrencyLimiter for atomic INCR-then-check.

        Args:
            tenant_id: Tenant identifier

        Returns:
            True if slot acquired, False if at capacity
        """
        key = f"tenant:{tenant_id}:active_jobs"
        max_concurrent = self.settings.tenant_worker_concurrency_limit
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            result = await self.redis_client.eval(
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
                    "Slot acquisition failed (at capacity)",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": max_concurrent,
                    },
                )

            return acquired

        except Exception as exc:
            logger.warning(
                "Failed to acquire slot in CrawlService",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return False

    async def _mark_slot_preacquired(self, job_id: UUID, tenant_id: UUID) -> None:
        """Mark that we pre-acquired a slot for this job.

        Worker checks this flag to skip limiter.acquire() (slot already held).
        TTL ensures cleanup if job is never picked up.

        Args:
            job_id: Job identifier for the flag key
            tenant_id: Stored in value so worker can release slot even if tenant
                       injection fails. Consistent with Feeder's implementation.

        Raises on failure - caller must handle rollback to prevent double-acquire.
        """
        key = f"job:{job_id}:slot_preacquired"
        # Store tenant_id (same as Feeder) so worker can release slot on failure
        # Let exception propagate - caller handles rollback
        await self.redis_client.set(
            key, str(tenant_id), ex=self.settings.tenant_worker_semaphore_ttl_seconds
        )

    async def _release_slot(self, tenant_id: UUID) -> None:
        """Release a previously acquired slot (used when enqueue fails)."""
        key = f"tenant:{tenant_id}:active_jobs"
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            await self.redis_client.eval(self._release_slot_lua, 1, key, str(ttl))
        except Exception as exc:
            logger.warning(
                "Failed to release slot",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def release_job_resources(self, job_id: UUID, tenant_id: UUID) -> None:
        """Release slot and clean up flag for a failed/preempted job.

        Called by Safe Preemption (WebsiteCRUDService) when preempting stale jobs.
        Safe to call even if resources don't exist (idempotent).
        Double-release is handled gracefully by Lua script (counter clamps at 0).

        Args:
            job_id: Job ID to clean up flag for
            tenant_id: Tenant ID for slot release
        """
        # Release slot using Redis EVAL for atomic Lua script execution (best-effort)
        key = f"tenant:{tenant_id}:active_jobs"
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds
        try:
            # Note: redis_client.eval runs Lua script atomically on Redis server
            await self.redis_client.eval(self._release_slot_lua, 1, key, str(ttl))
        except Exception as exc:
            logger.warning(
                "Failed to release slot for preempted job",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "error": str(exc),
                },
            )

        # Delete pre-acquired flag (harmless if doesn't exist)
        flag_key = f"job:{job_id}:slot_preacquired"
        try:
            await self.redis_client.delete(flag_key)
        except Exception as flag_exc:
            logger.debug(
                "Failed to delete slot_preacquired flag during preemption",
                extra={"job_id": str(job_id), "error": str(flag_exc)},
            )

    async def _add_to_pending_queue(
        self,
        tenant_id: UUID,
        job_id: UUID,
        user_id: UUID,
        website: "Website",
        run_id: UUID,
    ) -> None:
        """Add job to pending queue for feeder to process later.

        Same format as scheduler uses, so feeder can process uniformly.
        """
        key = f"tenant:{tenant_id}:crawl_pending"

        job_data = {
            "job_id": str(job_id),
            "user_id": str(user_id),
            "website_id": str(website.id),
            "run_id": str(run_id),
            "url": website.url,
            "download_files": website.download_files,
            "crawl_type": website.crawl_type.value,
        }

        try:
            job_json = json.dumps(job_data, default=str, sort_keys=True)
            await self.redis_client.rpush(key, job_json)
            logger.info(
                "Added crawl to pending queue (at capacity)",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "website_id": str(website.id),
                    "url": website.url,
                },
            )
        except Exception as exc:
            logger.error(
                "Failed to add to pending queue",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "error": str(exc),
                },
            )
            # CRITICAL: Fail the job immediately to prevent orphaned DB records
            # Why: If rpush fails, job stays QUEUED in DB but never enters Redis.
            # Without this, job becomes zombie (blocks recrawl but never runs).
            # By marking FAILED, user can immediately retry.
            try:
                await self.task_service.job_service.fail_job(
                    job_id, error_message=f"Failed to queue: {exc}"
                )
                logger.info(
                    "Marked orphaned job as FAILED after rpush failure",
                    extra={"job_id": str(job_id)},
                )
            except Exception as fail_exc:
                # Best effort - orphan cleanup will catch it eventually
                logger.warning(
                    "Could not fail orphaned job",
                    extra={"job_id": str(job_id), "error": str(fail_exc)},
                )
            raise

    async def _enqueue_to_arq(
        self,
        job_id: UUID,
        website: "Website",
        run_id: UUID,
    ) -> None:
        """Enqueue crawl job directly to ARQ."""
        from intric.jobs.job_models import Task
        from intric.websites.crawl_dependencies.crawl_models import CrawlTask

        params = CrawlTask(
            user_id=website.user_id,
            website_id=website.id,
            run_id=run_id,
            url=website.url,
            download_files=website.download_files,
            crawl_type=website.crawl_type,
        )

        await job_manager.enqueue(
            task=Task.CRAWL,
            job_id=job_id,
            params=params,
        )

    async def crawl(self, website: "Website") -> CrawlRun:
        """Start a crawl for a website with optimistic slot acquisition.

        When feeder is enabled:
        1. Create CrawlRun and Job records in DB
        2. Try to acquire concurrency slot atomically
        3. If acquired: mark flag and enqueue directly to ARQ
        4. If at capacity: add to pending queue for feeder

        When feeder is disabled:
        - Original direct enqueue behavior
        """
        # Create crawl run record
        crawl_run = CrawlRun.create(website=website)
        crawl_run = await self.repo.add(crawl_run=crawl_run)

        if self.settings.crawl_feeder_enabled:
            # Optimistic Acquire Pattern
            # Step 1: Create job record WITHOUT enqueueing to ARQ
            crawl_job = await self.task_service.queue_crawl(
                name=website.name,
                run_id=crawl_run.id,
                website_id=website.id,
                url=website.url,
                download_files=website.download_files,
                crawl_type=website.crawl_type,
                enqueue=False,  # Don't enqueue yet - we'll decide based on capacity
            )

            # Step 2: Try to acquire slot atomically
            slot_acquired = await self._try_acquire_slot(website.tenant_id)

            if slot_acquired:
                # Fast path: Capacity available
                try:
                    # Mark flag BEFORE enqueueing (safe hand-off)
                    # Must be inside try block - if mark fails, rollback slot
                    await self._mark_slot_preacquired(crawl_job.id, website.tenant_id)

                    # Enqueue directly to ARQ
                    await self._enqueue_to_arq(crawl_job.id, website, crawl_run.id)
                    logger.debug(
                        "Crawl enqueued directly (slot pre-acquired)",
                        extra={
                            "job_id": str(crawl_job.id),
                            "website_id": str(website.id),
                            "tenant_id": str(website.tenant_id),
                        },
                    )
                except Exception as exc:
                    # Rollback: delete flag (if it was set) and release slot
                    try:
                        await self.redis_client.delete(
                            f"job:{crawl_job.id}:slot_preacquired"
                        )
                    except Exception as flag_exc:
                        logger.debug(
                            "Failed to delete slot_preacquired flag during rollback",
                            extra={"job_id": str(crawl_job.id), "error": str(flag_exc)},
                        )
                    await self._release_slot(website.tenant_id)

                    # Fail the job to prevent orphaned DB records
                    # This prevents "Crawl already in progress" blocking future crawls
                    # Note: CrawlRun.status derives from Job.status (no status column on CrawlRuns)
                    try:
                        await self.task_service.job_service.fail_job(
                            crawl_job.id, error_message=f"Enqueue failed: {exc}"
                        )
                    except Exception:
                        pass  # Best effort - will be cleaned up by orphan cleanup

                    logger.error(
                        "Failed to enqueue crawl, rolled back slot and failed job",
                        extra={
                            "job_id": str(crawl_job.id),
                            "crawl_run_id": str(crawl_run.id),
                            "error": str(exc),
                        },
                    )
                    raise
            else:
                # Slow path: At capacity - add to pending queue
                await self._add_to_pending_queue(
                    tenant_id=website.tenant_id,
                    job_id=crawl_job.id,
                    user_id=website.user_id,
                    website=website,
                    run_id=crawl_run.id,
                )

            # Update crawl run with job ID
            crawl_run.update(job_id=crawl_job.id)
            crawl_run = await self.repo.update(crawl_run=crawl_run)

        else:
            # Feeder disabled: Original direct enqueue behavior
            crawl_job = await self.task_service.queue_crawl(
                name=website.name,
                run_id=crawl_run.id,
                website_id=website.id,
                url=website.url,
                download_files=website.download_files,
                crawl_type=website.crawl_type,
            )

            crawl_run.update(job_id=crawl_job.id)
            crawl_run = await self.repo.update(crawl_run=crawl_run)

        return crawl_run
