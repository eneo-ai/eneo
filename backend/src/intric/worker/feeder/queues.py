"""Queue management for crawl job processing.

Provides clean abstractions for pending queue operations and job enqueueing,
extracted from the monolithic CrawlFeeder class for better testability.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from uuid import UUID

from typing_extensions import TypedDict

from intric.main.logging import get_logger
from intric.websites.domain.crawl_run import CrawlType
from intric.worker.feeder.crawl_enqueue import (
    CrawlEnqueueDuplicate,
    CrawlEnqueueFailed,
    CrawlEnqueueResult,
    enqueue_crawl_job,
)
from intric.worker.redis.client import (
    redis_lrange_bytes,
    redis_lrem_exact,
    redis_rpush_text,
)

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = get_logger(__name__)


class CrawlPendingJobData(TypedDict):
    job_id: str
    user_id: str
    website_id: str
    run_id: str
    url: str
    download_files: bool
    crawl_type: str


class PendingCrawlPayload(TypedDict, total=False):
    job_id: str
    user_id: str
    website_id: str
    run_id: str
    url: str
    download_files: bool
    crawl_type: str


def _pending_job_data_from_pairs(
    pairs: list[tuple[str, object]],
) -> PendingCrawlPayload:
    # Incomplete payloads continue to JobEnqueuer, which owns failure bucketing.
    job_data: PendingCrawlPayload = {}
    for key, value in pairs:
        if key in {"job_id", "user_id", "website_id", "run_id", "url", "crawl_type"}:
            if isinstance(value, str):
                job_data[key] = value
        elif key == "download_files" and isinstance(value, bool):
            job_data["download_files"] = value
    return job_data


def _loads_pending_job_data(raw_json: str) -> PendingCrawlPayload:
    parsed_payloads: list[PendingCrawlPayload] = []

    def collect_payload(pairs: list[tuple[str, object]]) -> PendingCrawlPayload:
        payload = _pending_job_data_from_pairs(pairs)
        parsed_payloads.append(payload)
        return payload

    # object_pairs_hook keeps JSON shape conversion typed without a local cast.
    loaded_object: object = json.loads(raw_json, object_pairs_hook=collect_payload)
    if not isinstance(loaded_object, dict):
        raise ValueError("pending crawl payload must be a JSON object")
    return parsed_payloads[-1]


class PendingQueueAddError(RuntimeError):
    """Raised when a pending crawl job cannot be written to Redis."""

    def __init__(self, *, tenant_id: UUID, cause: Exception) -> None:
        self.tenant_id = tenant_id
        super().__init__(
            f"Failed to add crawl to pending queue for tenant {tenant_id}: {cause}"
        )


class PendingQueue:
    """Manages the Redis pending crawl queue for a tenant.

    Provides atomic operations for retrieving and removing jobs from
    the FIFO queue, with poison message handling.

    Args:
        redis_client: Async Redis connection.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        super().__init__()
        self._redis = redis_client

    @staticmethod
    def _key(tenant_id: UUID) -> str:
        """Generate the Redis key for a tenant's pending queue."""
        return f"tenant:{tenant_id}:crawl_pending"

    async def get_pending(
        self, tenant_id: UUID, limit: int
    ) -> list[tuple[bytes, PendingCrawlPayload]]:
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
            pending_bytes = await redis_lrange_bytes(self._redis, key, 0, limit - 1)

            if not pending_bytes:
                return []

            pending_jobs: list[tuple[bytes, PendingCrawlPayload]] = []
            for raw_bytes in pending_bytes:
                try:
                    pending_jobs.append(
                        (raw_bytes, _loads_pending_job_data(raw_bytes.decode()))
                    )
                except (json.JSONDecodeError, ValueError) as parse_exc:
                    # Remove poison message to prevent infinite retry loop
                    logger.warning(
                        "Removing invalid JSON from pending queue (poison message)",
                        extra={"tenant_id": str(tenant_id), "error": str(parse_exc)},
                    )
                    try:
                        await redis_lrem_exact(self._redis, key, raw_bytes)
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
            await redis_lrem_exact(self._redis, key, raw_bytes)
        except Exception as exc:
            logger.warning(
                "Failed to remove from pending queue",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def add(self, tenant_id: UUID, job_data: CrawlPendingJobData) -> None:
        """Add a crawl job to the pending queue for feeder processing.

        Appends to the right side of the list (FIFO queue). The job_data
        dict should contain all fields needed by the feeder to enqueue
        to ARQ: job_id, user_id, website_id, run_id, url, download_files,
        crawl_type.

        Args:
            tenant_id: Tenant identifier.
            job_data: Job parameters dict with serializable values.

        Raises:
            PendingQueueAddError: If Redis rejects the write.
        """
        key = self._key(tenant_id)

        try:
            # Serialize with sorted keys for deterministic bytes
            job_json = json.dumps(job_data, default=str, sort_keys=True)
            await redis_rpush_text(self._redis, key, job_json)

            logger.debug(
                "Added crawl to pending queue",
                extra={
                    "tenant_id": str(tenant_id),
                    "website_id": job_data.get("website_id"),
                    "url": job_data.get("url"),
                },
            )

        except Exception as exc:
            raise PendingQueueAddError(tenant_id=tenant_id, cause=exc) from exc


class JobEnqueuer:
    """Enqueues crawl jobs to ARQ with idempotency handling.

    Handles job reconstruction and duplicate detection for safe retries.
    """

    async def enqueue(
        self, job_data: PendingCrawlPayload, tenant_id: UUID
    ) -> CrawlEnqueueResult:
        """Enqueue a crawl job to ARQ using pre-created job record.

        Job and CrawlRun records are already created by the scheduler.
        The feeder handles ARQ enqueueing with deterministic job_id for idempotency.

        Args:
            job_data: Job parameters from pending queue (includes job_id from DB).
            tenant_id: Tenant identifier.

        Returns:
            A typed enqueue outcome. Duplicate means ARQ reported an existing
            deterministic job id; failed means the pending payload could not be
            parsed or ARQ raised.
        """
        try:
            raw_job_id = job_data.get("job_id")
            if not isinstance(raw_job_id, str):
                raise TypeError("job_id is required")
            job_id = UUID(raw_job_id)
        except (KeyError, ValueError, TypeError) as exc:
            logger.error(
                "Invalid job_id in pending job data",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_data": job_data,
                    "error": str(exc),
                },
            )
            nil_job_id = UUID("00000000-0000-0000-0000-000000000000")
            return CrawlEnqueueFailed(job_id=nil_job_id, error=exc)

        try:
            raw_user_id = job_data.get("user_id")
            raw_website_id = job_data.get("website_id")
            raw_run_id = job_data.get("run_id")
            url = job_data.get("url")
            download_files = job_data.get("download_files")
            raw_crawl_type = job_data.get("crawl_type")
            if not (
                isinstance(raw_user_id, str)
                and isinstance(raw_website_id, str)
                and isinstance(raw_run_id, str)
                and isinstance(url, str)
                and isinstance(download_files, bool)
                and isinstance(raw_crawl_type, str)
            ):
                raise TypeError("pending crawl job data is incomplete")

            user_id = UUID(raw_user_id)
            website_id = UUID(raw_website_id)
            run_id = UUID(raw_run_id)
            crawl_type = CrawlType(raw_crawl_type)
        except (KeyError, ValueError, TypeError) as exc:
            logger.error(
                "Invalid pending crawl job data",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_data": job_data,
                    "error": str(exc),
                },
            )
            return CrawlEnqueueFailed(job_id=job_id, error=exc)

        result = await enqueue_crawl_job(
            job_id=job_id,
            user_id=user_id,
            website_id=website_id,
            run_id=run_id,
            url=url,
            download_files=download_files,
            crawl_type=crawl_type,
        )

        if isinstance(result, CrawlEnqueueDuplicate):
            return result
        if isinstance(result, CrawlEnqueueFailed):
            logger.error(
                "Failed to enqueue crawl job from feeder",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_data": job_data,
                    "error": str(result.error),
                },
            )
            return result

        logger.debug(
            "Enqueued crawl job from feeder",
            extra={
                "tenant_id": str(tenant_id),
                "job_id": str(job_id),
                "website_id": str(website_id),
                "url": url,
            },
        )
        return result
