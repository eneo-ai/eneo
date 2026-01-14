"""Queue management for crawl job processing.

Provides clean abstractions for pending queue operations and job enqueueing,
extracted from the monolithic CrawlFeeder class for better testability.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from intric.jobs.job_manager import job_manager
from intric.main.logging import get_logger

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


class PendingQueue:
    """Manages the Redis pending crawl queue for a tenant.

    Provides atomic operations for retrieving and removing jobs from
    the FIFO queue, with poison message handling.

    Args:
        redis_client: Async Redis connection.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def _key(tenant_id: UUID) -> str:
        """Generate the Redis key for a tenant's pending queue."""
        return f"tenant:{tenant_id}:crawl_pending"

    async def get_pending(
        self, tenant_id: UUID, limit: int
    ) -> list[tuple[bytes, dict]]:
        """Get pending crawl jobs from the queue.

        Args:
            tenant_id: Tenant identifier.
            limit: Maximum number of jobs to retrieve.

        Returns:
            List of tuples: (raw_bytes, parsed_job_data).
            Raw bytes are preserved for exact LREM matching to avoid
            serialization mismatch issues.
        """
        key = self._key(tenant_id)

        try:
            pending_bytes = await self._redis.lrange(key, 0, limit - 1)

            if not pending_bytes:
                return []

            pending_jobs = []
            for raw_bytes in pending_bytes:
                try:
                    job_data = json.loads(raw_bytes.decode())
                    pending_jobs.append((raw_bytes, job_data))
                except json.JSONDecodeError as parse_exc:
                    # Remove poison message to prevent infinite retry loop
                    logger.warning(
                        "Removing invalid JSON from pending queue (poison message)",
                        extra={"tenant_id": str(tenant_id), "error": str(parse_exc)},
                    )
                    try:
                        await self._redis.lrem(key, 1, raw_bytes)
                    except Exception:
                        pass  # Best effort removal
                    continue

            return pending_jobs

        except Exception as exc:
            logger.warning(
                "Failed to get pending crawls",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return []

    async def remove(self, tenant_id: UUID, raw_bytes: bytes) -> None:
        """Remove job from pending queue after successful enqueue.

        Uses exact raw bytes from lrange to ensure LREM matches.
        Re-serializing could produce different bytes than the original push.

        Args:
            tenant_id: Tenant identifier.
            raw_bytes: Original raw bytes from lrange (NOT re-serialized).
        """
        key = self._key(tenant_id)

        try:
            await self._redis.lrem(key, 1, raw_bytes)
        except Exception as exc:
            logger.warning(
                "Failed to remove from pending queue",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def add(self, tenant_id: UUID, job_data: dict) -> bool:
        """Add a crawl job to the pending queue for feeder processing.

        Appends to the right side of the list (FIFO queue). The job_data
        dict should contain all fields needed by the feeder to enqueue
        to ARQ: job_id, user_id, website_id, run_id, url, download_files,
        crawl_type.

        Args:
            tenant_id: Tenant identifier.
            job_data: Job parameters dict with serializable values.

        Returns:
            True if successfully added, False on error.
        """
        key = self._key(tenant_id)

        try:
            # Serialize with sorted keys for deterministic bytes
            job_json = json.dumps(job_data, default=str, sort_keys=True)
            await self._redis.rpush(key, job_json)

            logger.debug(
                "Added crawl to pending queue",
                extra={
                    "tenant_id": str(tenant_id),
                    "website_id": job_data.get("website_id"),
                    "url": job_data.get("url"),
                },
            )
            return True

        except Exception as exc:
            logger.error(
                "Failed to add to pending queue",
                extra={
                    "tenant_id": str(tenant_id),
                    "error": str(exc),
                },
            )
            return False


class JobEnqueuer:
    """Enqueues crawl jobs to ARQ with idempotency handling.

    Handles job reconstruction and duplicate detection for safe retries.
    """

    # Patterns indicating a duplicate job (case-insensitive matching)
    _DUPLICATE_PATTERNS = ("already exists", "duplicate", "job exists")

    async def enqueue(self, job_data: dict, tenant_id: UUID) -> tuple[bool, bool, UUID]:
        """Enqueue a crawl job to ARQ using pre-created job record.

        Job and CrawlRun records are already created by the scheduler.
        The feeder handles ARQ enqueueing with deterministic job_id for idempotency.

        Args:
            job_data: Job parameters from pending queue (includes job_id from DB).
            tenant_id: Tenant identifier.

        Returns:
            Tuple of (success: bool, is_duplicate: bool, job_id: UUID).
            is_duplicate=True when job already exists in ARQ (idempotent success).
            Returns nil UUID on invalid job_id.
        """
        # Parse job_id early for clean error handling
        try:
            job_id = UUID(job_data["job_id"])
        except (KeyError, ValueError, TypeError) as exc:
            logger.error(
                "Invalid job_id in pending job data",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_data": job_data,
                    "error": str(exc),
                },
            )
            return False, False, UUID("00000000-0000-0000-0000-000000000000")

        try:
            from intric.jobs.job_models import Task
            from intric.websites.crawl_dependencies.crawl_models import (
                CrawlTask,
                CrawlType,
            )

            params = CrawlTask(
                user_id=UUID(job_data["user_id"]),
                website_id=UUID(job_data["website_id"]),
                run_id=UUID(job_data["run_id"]),
                url=job_data["url"],
                download_files=job_data["download_files"],
                crawl_type=CrawlType(job_data["crawl_type"]),
            )

            await job_manager.enqueue(
                task=Task.CRAWL,
                job_id=job_id,
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
            return True, False, job_id  # success, not duplicate

        except Exception as exc:
            return self._handle_enqueue_error(exc, job_id, job_data, tenant_id)

    def _handle_enqueue_error(
        self, exc: Exception, job_id: UUID, job_data: dict, tenant_id: UUID
    ) -> tuple[bool, bool, UUID]:
        """Handle enqueue errors with duplicate detection.

        Duplicate jobs are treated as success for idempotency.
        If the feeder crashes after enqueue but before LREM, the job stays
        in pending. On retry, ARQ returns "already exists" - we treat this
        as SUCCESS so LREM proceeds and clears the job.

        IMPORTANT: Caller must release slot when is_duplicate=True, since
        the original enqueue already acquired a slot.

        Args:
            exc: The exception that occurred.
            job_id: The job identifier.
            job_data: Original job data for logging.
            tenant_id: Tenant identifier.

        Returns:
            Tuple of (success: bool, is_duplicate: bool, job_id: UUID).
        """
        error_msg = str(exc).lower()

        is_duplicate = any(pattern in error_msg for pattern in self._DUPLICATE_PATTERNS)

        if is_duplicate:
            # Debug-level per-job log; summary is at INFO in crawl_feeder.py
            logger.debug(
                "Job already in ARQ queue (idempotent), treating as success",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "url": job_data.get("url"),
                    "reason": "duplicate_job_id",
                },
            )
            return True, True, job_id  # success, IS duplicate

        logger.error(
            "Failed to enqueue crawl job from feeder",
            extra={
                "tenant_id": str(tenant_id),
                "job_data": job_data,
                "error": str(exc),
            },
        )
        return False, False, job_id  # failed, not duplicate
