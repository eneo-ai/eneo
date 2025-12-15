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
import socket
from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis.asyncio as aioredis

from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.worker.feeder.capacity import CapacityManager
from intric.worker.feeder.election import LeaderElection
from intric.worker.feeder.queues import JobEnqueuer, PendingQueue
from intric.worker.feeder.watchdog import OrphanWatchdog

logger = get_logger(__name__)


class CrawlFeeder:
    """Meters crawl job enqueue rate based on available concurrency capacity.

    Why: Prevents burst overload by only enqueueing when capacity exists.
    Observes the existing TenantConcurrencyLimiter state (active_jobs counter).

    Note: This service is long-running and manages its own DB sessions and Redis client.
    It does NOT depend on a request-scoped Container to avoid session lifecycle issues.
    """

    def __init__(self):
        self.settings = get_settings()
        self._running = False
        self._redis_client: aioredis.Redis | None = None
        self._pending_queue: PendingQueue | None = None
        self._job_enqueuer: JobEnqueuer = JobEnqueuer()  # Stateless, init immediately
        self._capacity_manager: CapacityManager | None = None
        self._leader_election: LeaderElection | None = None
        self._orphan_watchdog: OrphanWatchdog | None = None
        # Cache worker_id at init (gethostname is sync, may trigger DNS)
        self._worker_id = socket.gethostname()
        # Heartbeat tracking for idle status logging
        self._last_heartbeat: datetime | None = None
        self._heartbeat_interval = 300

    async def _cleanup_orphaned_crawl_runs(self) -> None:
        """Clean up CrawlRuns with NULL job_id older than timeout threshold.

        Why: These orphaned records occur when:
        - Jobs are deleted (CASCADE sets job_id to NULL)
        - CrawlRun creation fails after insert but before job_id is set

        CrawlRun.status is derived from Job.status. With NULL job_id, status
        defaults to QUEUED but these are ghost records that accumulate.
        Uses same timeout threshold as job cleanup for consistency.
        """
        from sqlalchemy import delete, and_

        from intric.database.database import sessionmanager
        from intric.database.tables.websites_table import CrawlRuns

        timeout_hours = self.settings.orphan_crawl_run_timeout_hours
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

        try:
            async with sessionmanager.session() as session, session.begin():
                cleanup_stmt = (
                    delete(CrawlRuns)
                    .where(
                        and_(
                            CrawlRuns.job_id == None,
                            CrawlRuns.updated_at < cutoff_time,
                        )
                    )
                    .execution_options(synchronize_session=False)
                )
                result = await session.execute(cleanup_stmt)
                if result.rowcount > 0:
                    logger.info(
                        "Cleaned up orphaned CrawlRuns with NULL job_id",
                        extra={"cleaned_count": result.rowcount},
                    )
        except Exception as exc:
            logger.warning(
                "Failed to cleanup orphaned CrawlRuns",
                extra={"error": str(exc)},
            )

    async def _process_tenant_queue(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> None:
        """Process pending crawls for one tenant.

        Atomically acquires slots and enqueues jobs when capacity exists.
        Slot is acquired BEFORE enqueueing to eliminate race conditions.

        Args:
            tenant_id: Tenant identifier.
            redis_client: Redis connection.
        """
        # Fetch tenant-specific crawler settings (supports per-tenant overrides)
        tenant_crawler_settings = await self._capacity_manager.get_tenant_settings(
            tenant_id
        )

        # Check available capacity (read-only hint for batch sizing)
        available = await self._capacity_manager.get_available_capacity(
            tenant_id, tenant_crawler_settings
        )

        if available <= 0:
            return  # No capacity, skip this tenant

        # Get pending jobs (limit to available capacity and batch size)
        # Why: Batch size prevents enqueueing too many at once
        batch_size = get_crawler_setting(
            "crawl_feeder_batch_size",
            tenant_crawler_settings,
            default=self.settings.crawl_feeder_batch_size,
        )
        limit = min(available, batch_size)
        pending_jobs = await self._pending_queue.get_pending(tenant_id, limit)

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

        # pending_jobs is list of (raw_bytes, job_data) tuples
        # raw_bytes preserved for exact LREM matching
        for raw_bytes, job_data in pending_jobs:
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

            # Atomically acquire slot BEFORE enqueueing to eliminate race condition
            slot_acquired = await self._capacity_manager.try_acquire_slot(
                tenant_id, tenant_crawler_settings
            )

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

            # Mark flag BEFORE enqueueing for safe hand-off to worker
            try:
                await self._capacity_manager.mark_slot_preacquired(
                    job_id, tenant_id, tenant_crawler_settings
                )
            except Exception as mark_exc:
                # Mark failed - MUST release slot and skip enqueue to prevent double-acquire
                logger.error(
                    "Failed to mark slot pre-acquired, rolling back slot",
                    extra={"job_id": str(job_id), "tenant_id": str(tenant_id), "error": str(mark_exc)},
                )
                await self._capacity_manager.release_slot(tenant_id)
                failed_count += 1
                continue

            # Enqueue to ARQ
            success, returned_job_id = await self._job_enqueuer.enqueue(job_data, tenant_id)

            if success:
                # Remove from pending queue using exact raw bytes
                await self._pending_queue.remove(tenant_id, raw_bytes)
                enqueued_count += 1
            else:
                # Enqueue failed - rollback: delete flag and release slot
                try:
                    await redis_client.delete(f"job:{job_id}:slot_preacquired")
                except Exception:
                    pass  # Best effort cleanup
                await self._capacity_manager.release_slot(tenant_id)
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

        Note: This service manages its own Redis client lifecycle.
        It does NOT depend on a Container to avoid session scope issues.
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

        # Create own Redis client (long-running service manages its own lifecycle)
        try:
            redis_url = f"redis://{self.settings.redis_host}:{self.settings.redis_port}"
            redis_kwargs = {"decode_responses": False}  # Raw bytes for LREM matching
            redis_db = getattr(self.settings, "redis_db", None)
            if redis_db is not None:
                redis_kwargs["db"] = redis_db

            self._redis_client = aioredis.Redis.from_url(redis_url, **redis_kwargs)
            redis_client = self._redis_client
            self._pending_queue = PendingQueue(redis_client)
            self._capacity_manager = CapacityManager(redis_client, self.settings)
            self._leader_election = LeaderElection(redis_client, self._worker_id)
            self._orphan_watchdog = OrphanWatchdog(redis_client, self.settings)
        except Exception as exc:
            logger.error(f"Failed to create Redis client: {exc}")
            return

        try:
            while self._running:
                try:
                    # Try to become leader (prevents multiple feeders running)
                    if not await self._leader_election.try_acquire():
                        await asyncio.sleep(5)
                        continue

                    # We are the leader - run orphan cleanup then process queues
                    await self._orphan_watchdog.run_cleanup()
                    await self._cleanup_orphaned_crawl_runs()

                    # Find all tenants with pending crawls (SCAN for production safety)
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
                    processed_any = False
                    for tenant_id in tenant_ids:
                        try:
                            await self._process_tenant_queue(tenant_id, redis_client)
                            processed_any = True
                        except Exception as exc:
                            logger.error(
                                f"Error processing tenant queue: {exc}",
                                extra={"tenant_id": str(tenant_id)},
                            )
                            continue  # Don't let one tenant's error stop others

                    # Heartbeat: log idle status every 5 minutes to reduce log spam
                    now = datetime.now(timezone.utc)
                    if not processed_any:
                        if (
                            self._last_heartbeat is None
                            or (now - self._last_heartbeat).total_seconds() >= self._heartbeat_interval
                        ):
                            logger.info("Feeder heartbeat: idle, no pending crawls")
                            self._last_heartbeat = now
                    else:
                        # Reset heartbeat timer after actual work
                        self._last_heartbeat = now

                    # Refresh leader lock before sleeping
                    await self._leader_election.refresh()

                    # Sleep until next cycle (use shortest interval among active tenants)
                    sleep_interval = await self._capacity_manager.get_minimum_feeder_interval()
                    await asyncio.sleep(sleep_interval)

                except Exception as exc:
                    logger.error(f"Error in feeder loop: {exc}")
                    # Continue running - feeder should be resilient
                    sleep_interval = await self._capacity_manager.get_minimum_feeder_interval()
                    await asyncio.sleep(sleep_interval)
        finally:
            await self._close_redis()

    async def _close_redis(self) -> None:
        """Close Redis client if it exists."""
        if self._redis_client:
            try:
                await self._redis_client.aclose()
                self._redis_client = None
                logger.debug("Feeder Redis client closed")
            except Exception as exc:
                logger.warning(f"Error closing Redis client: {exc}")

    async def stop(self) -> None:
        """Stop the feeder loop gracefully."""
        logger.info("Stopping crawl feeder service")
        self._running = False
        await self._close_redis()
