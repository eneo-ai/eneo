"""Crawl Service - Handles individual crawl requests with optimistic slot acquisition.

Implements "Optimistic Acquire" pattern for manual/bulk crawls:
- Try to acquire concurrency slot immediately
- If acquired: Direct to ARQ with pre-acquired flag (low latency)
- If at capacity: Add to pending queue for feeder (no retry storm)

This eliminates retry storms for manual crawls while maintaining low latency
for normal operations when capacity is available.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

import redis.asyncio as aioredis

from intric.jobs.job_manager import job_manager
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.main.models import Status
from intric.websites.domain.crawl_abort import (
    CrawlAbortConflict,
    CrawlAbortConflictCode,
    CrawlAbortNotFound,
    CrawlAbortResult,
    CrawlAbortSucceeded,
    CrawlAbortWebsite,
)
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlRun
from intric.websites.domain.crawl_terminal import (
    TerminalEvent,
    crawl_direct_enqueue_failure_message,
    crawl_pending_queue_enqueue_failure_message,
)
from intric.worker.feeder.crawl_enqueue import (
    CrawlEnqueueFailed,
    enqueue_crawl_job,
)
from intric.worker.feeder.queues import (
    CrawlPendingJobData,
    PendingQueue,
    PendingQueueAddError,
)
from intric.worker.redis.lua_scripts import LuaScripts

if TYPE_CHECKING:
    from intric.jobs.task_service import TaskService
    from intric.websites.domain.crawl_run_repo import (
        CrawlAbortTarget,
        CrawlRunRepository,
    )
    from intric.websites.domain.website import Website, WebsiteSparse

    CrawlableWebsite = Website | WebsiteSparse

logger = get_logger(__name__)


def _abort_website(target: "CrawlAbortTarget") -> CrawlAbortWebsite:
    return CrawlAbortWebsite(
        id=target.website_id,
        name=target.website_name or target.website_url,
    )


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

    def __init__(
        self,
        repo: "CrawlRunRepository",
        task_service: "TaskService",
        redis_client: aioredis.Redis,
    ):
        super().__init__()
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
        max_concurrent = self.settings.tenant_worker_concurrency_limit
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            result = await LuaScripts.acquire_slot(
                self.redis_client,
                tenant_id,
                max_concurrent,
                ttl,
            )

            acquired = result > 0

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
        key = LuaScripts.preacquired_slot_key(job_id)
        # Store tenant_id (same as Feeder) so worker can release slot on failure
        # Let exception propagate - caller handles rollback
        await self.redis_client.set(
            key, str(tenant_id), ex=self.settings.tenant_worker_semaphore_ttl_seconds
        )

    async def _release_slot(self, tenant_id: UUID) -> None:
        """Release a previously acquired slot after direct handoff setup fails."""
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            await LuaScripts.release_slot(self.redis_client, tenant_id, ttl)
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
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds
        try:
            await LuaScripts.release_slot(self.redis_client, tenant_id, ttl)
        except Exception as exc:
            logger.warning(
                "Failed to release slot for preempted job",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "error": str(exc),
                },
            )

        # Preemption handles an already-terminal job, so slot release can run before
        # flag deletion without a worker racing this handoff path.
        flag_key = LuaScripts.preacquired_slot_key(job_id)
        try:
            await self.redis_client.delete(flag_key)
        except Exception as flag_exc:
            logger.debug(
                "Failed to delete slot_preacquired flag during preemption",
                extra={"job_id": str(job_id), "error": str(flag_exc)},
            )

    async def _cleanup_aborted_queued_job(self, job_id: UUID, tenant_id: UUID) -> None:
        await PendingQueue(self.redis_client).remove_by_job_id(tenant_id, job_id)
        try:
            await job_manager.abort_job(job_id)
        except Exception as exc:
            logger.warning(
                "Failed to abort queued crawl in ARQ after terminal commit",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(tenant_id),
                    "error": str(exc),
                },
            )

        flag_key = LuaScripts.preacquired_slot_key(job_id)
        try:
            has_preacquired_slot = await self.redis_client.get(flag_key) is not None
        except Exception as exc:
            logger.warning(
                "Failed to inspect pre-acquired crawl slot during abort cleanup",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(tenant_id),
                    "error": str(exc),
                },
            )
            has_preacquired_slot = False

        # Pending-queue-only jobs do not own a tenant slot; releasing without the
        # handoff flag can decrement capacity for an unrelated running crawl.
        if has_preacquired_slot:
            await self.release_job_resources(job_id, tenant_id)

    async def abort_queued_crawl(
        self,
        *,
        job_id: UUID,
        tenant_id: UUID,
    ) -> CrawlAbortResult:
        target = await self.repo.abort_target_for_tenant(
            job_id=job_id,
            tenant_id=tenant_id,
        )
        if target is None:
            return CrawlAbortNotFound(job_id=job_id)

        if (
            target.status == Status.FAILED
            and target.outcome_code == CrawlOutcomeCode.CRAWL_ABORTED
        ):
            await self._cleanup_aborted_queued_job(job_id, tenant_id)
            return CrawlAbortSucceeded(
                job_id=job_id,
                crawl_run_id=target.crawl_run_id,
                website=_abort_website(target),
                already_terminal=True,
            )

        if target.status == Status.IN_PROGRESS:
            return CrawlAbortConflict(
                job_id=job_id,
                code=CrawlAbortConflictCode.RUNNING_ABORT_NOT_IMPLEMENTED,
            )

        if target.status != Status.QUEUED:
            return CrawlAbortConflict(
                job_id=job_id,
                code=CrawlAbortConflictCode.CRAWL_NOT_ABORTABLE,
            )

        result = await self.repo.commit_terminal(
            TerminalEvent(
                crawl_run_id=target.crawl_run_id,
                job_id=job_id,
                job_status=Status.FAILED,
                outcome_code=CrawlOutcomeCode.CRAWL_ABORTED,
                finished_at=datetime.now(timezone.utc),
                result_location="Crawl aborted by tenant admin",
                allowed_current_job_statuses=(Status.QUEUED,),
            )
        )
        if result.job_rows_updated == 0:
            return CrawlAbortConflict(
                job_id=job_id,
                code=CrawlAbortConflictCode.CRAWL_NOT_ABORTABLE,
            )

        await self._cleanup_aborted_queued_job(job_id, tenant_id)
        return CrawlAbortSucceeded(
            job_id=job_id,
            crawl_run_id=target.crawl_run_id,
            website=_abort_website(target),
            already_terminal=False,
        )

    async def _add_to_pending_queue(
        self,
        tenant_id: UUID,
        job_id: UUID,
        user_id: UUID,
        website: "CrawlableWebsite",
        run_id: UUID,
    ) -> None:
        """Add job to pending queue for feeder to process later.

        Same format as scheduler uses, so feeder can process uniformly.
        """
        job_data: CrawlPendingJobData = {
            "job_id": str(job_id),
            "user_id": str(user_id),
            "website_id": str(website.id),
            "run_id": str(run_id),
            "url": website.url,
            "download_files": website.download_files,
            "crawl_type": website.crawl_type.value,
        }

        try:
            await PendingQueue(self.redis_client).add(tenant_id, job_data)
            logger.info(
                "Added crawl to pending queue (at capacity)",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "website_id": str(website.id),
                    "url": website.url,
                },
            )
        except PendingQueueAddError as exc:
            failure_message = crawl_pending_queue_enqueue_failure_message(exc)
            logger.error(
                failure_message,
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "error": str(exc),
                },
            )
            try:
                await self.repo.commit_terminal(
                    TerminalEvent(
                        crawl_run_id=run_id,
                        job_id=job_id,
                        job_status=Status.FAILED,
                        outcome_code=CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED,
                        finished_at=datetime.now(timezone.utc),
                        result_location=failure_message,
                    )
                )
                logger.info(
                    "Committed crawl terminal failure after pending queue write failure",
                    extra={"job_id": str(job_id)},
                )
            except Exception as terminal_exc:
                logger.warning(
                    "Terminal commit after pending queue failure failed",
                    extra={"job_id": str(job_id), "error": str(terminal_exc)},
                )
            raise

    async def _enqueue_to_arq(
        self,
        job_id: UUID,
        website: "CrawlableWebsite",
        run_id: UUID,
    ) -> None:
        """Enqueue crawl job directly to ARQ."""
        result = await enqueue_crawl_job(
            job_id=job_id,
            user_id=website.user_id,
            website_id=website.id,
            run_id=run_id,
            url=website.url,
            download_files=website.download_files,
            crawl_type=website.crawl_type,
        )
        if isinstance(result, CrawlEnqueueFailed):
            raise result.error

    async def crawl(self, website: "CrawlableWebsite") -> CrawlRun:
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
                name=website.name or website.url,
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
                    failure_message = crawl_direct_enqueue_failure_message(exc)
                    # Rollback capacity before terminal commit so a failed DB write
                    # cannot leave future crawls blocked by a leaked slot.
                    try:
                        await self.redis_client.delete(
                            LuaScripts.preacquired_slot_key(crawl_job.id)
                        )
                    except Exception as flag_exc:
                        logger.debug(
                            "Failed to delete slot_preacquired flag during rollback",
                            extra={"job_id": str(crawl_job.id), "error": str(flag_exc)},
                        )
                    await self._release_slot(website.tenant_id)

                    try:
                        await self.repo.commit_terminal(
                            TerminalEvent(
                                crawl_run_id=crawl_run.id,
                                job_id=crawl_job.id,
                                job_status=Status.FAILED,
                                outcome_code=(
                                    CrawlOutcomeCode.CRAWL_DIRECT_ENQUEUE_FAILED
                                ),
                                finished_at=datetime.now(timezone.utc),
                                result_location=failure_message,
                            )
                        )
                        logger.info(
                            "Committed crawl terminal failure after direct enqueue failure",
                            extra={"job_id": str(crawl_job.id)},
                        )
                    except Exception as terminal_exc:
                        logger.warning(
                            "Terminal commit after direct crawl enqueue failure failed",
                            extra={
                                "job_id": str(crawl_job.id),
                                "error": str(terminal_exc),
                            },
                        )

                    logger.error(
                        "Failed to enqueue crawl directly and rolled back slot",
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
                name=website.name or website.url,
                run_id=crawl_run.id,
                website_id=website.id,
                url=website.url,
                download_files=website.download_files,
                crawl_type=website.crawl_type,
            )

            crawl_run.update(job_id=crawl_job.id)
            crawl_run = await self.repo.update(crawl_run=crawl_run)

        return crawl_run
