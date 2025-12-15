"""Heartbeat monitor for long-running crawl tasks.

Handles three responsibilities:
1. DB heartbeat: Touch job record to prevent stale job detection
2. Redis TTL refresh: Keep semaphore counter and job flag keys alive
3. Preemption detection: Check if job was externally marked as FAILED
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from intric.tenants.tenant import Tenant

logger = logging.getLogger(__name__)


class HeartbeatFailedError(Exception):
    """Raised when consecutive heartbeat failures exceed threshold."""

    def __init__(self, consecutive_failures: int, max_failures: int):
        self.consecutive_failures = consecutive_failures
        self.max_failures = max_failures
        super().__init__(
            f"Heartbeat failures ({consecutive_failures}) exceeded threshold ({max_failures})"
        )


class JobPreemptedError(Exception):
    """Raised when job is detected as preempted (externally marked FAILED)."""

    def __init__(self, job_id: UUID):
        self.job_id = job_id
        super().__init__(f"Job {job_id} was preempted")


class HeartbeatMonitor:
    """Manages heartbeat operations for a single crawl job.

    Encapsulates timing state and failure tracking. Call tick() from the
    main crawl loop - it handles interval checking internally.

    Example:
        monitor = HeartbeatMonitor(
            job_id=job_id,
            redis_client=redis,
            tenant=tenant,
            interval_seconds=300,
            max_failures=3,
            semaphore_ttl_seconds=600,
        )

        for page in crawl.pages:
            await monitor.tick()  # Raises on preemption or failure threshold
            process(page)
    """

    def __init__(
        self,
        job_id: UUID,
        redis_client: "Redis | None",
        tenant: "Tenant | None",
        interval_seconds: int,
        max_failures: int,
        semaphore_ttl_seconds: int,
    ):
        self._job_id = job_id
        self._redis_client = redis_client
        self._tenant = tenant
        self._interval_seconds = interval_seconds
        self._max_failures = max_failures
        self._semaphore_ttl_seconds = semaphore_ttl_seconds

        self._last_beat_time: float = 0.0
        self._consecutive_failures: int = 0

    @property
    def consecutive_failures(self) -> int:
        """Current count of consecutive Redis heartbeat failures."""
        return self._consecutive_failures

    async def tick(self) -> None:
        """Execute heartbeat if interval has elapsed.

        Call this from the main crawl loop. It's a no-op if called before
        the interval has elapsed.

        Raises:
            HeartbeatFailedError: If consecutive failures exceed max_failures
            JobPreemptedError: If job was externally marked as FAILED
        """
        current_time = time.time()
        if current_time - self._last_beat_time < self._interval_seconds:
            return

        await self._execute_heartbeat()
        self._last_beat_time = current_time

    async def _execute_heartbeat(self) -> None:
        """Perform the actual heartbeat operations."""
        await self._touch_job_in_db()
        await self._refresh_redis_ttl()
        await self._check_preemption()

    async def _touch_job_in_db(self) -> None:
        """Update job's updated_at timestamp in database.

        Uses a short-lived session to avoid holding connections during crawl.
        DB failures are logged but don't trigger termination - the crawl
        can continue even if DB is temporarily unreachable.
        """
        try:
            from intric.database.database import sessionmanager
            from intric.jobs.job_repo import JobRepository

            async with sessionmanager.session() as session:
                async with session.begin():
                    job_repo = JobRepository(session=session)
                    await job_repo.touch_job(self._job_id)

        except Exception as exc:
            logger.warning(
                f"DB heartbeat failed: {exc}",
                extra={"job_id": str(self._job_id)},
            )

    async def _refresh_redis_ttl(self) -> None:
        """Refresh TTL on Redis semaphore counter and job flag keys.

        Consecutive failures trigger termination to prevent zombie jobs
        that hold slots but aren't actually processing.

        Raises:
            HeartbeatFailedError: If consecutive failures exceed max_failures
        """
        if not self._redis_client or not self._tenant:
            return

        concurrency_key = f"tenant:{self._tenant.id}:active_jobs"
        flag_key = f"job:{self._job_id}:slot_preacquired"

        try:
            pipe = self._redis_client.pipeline(transaction=True)
            pipe.expire(concurrency_key, self._semaphore_ttl_seconds)
            pipe.expire(flag_key, self._semaphore_ttl_seconds)
            results = await pipe.execute()

            self._consecutive_failures = 0

            counter_refreshed = results[0] if len(results) > 0 else 0
            flag_refreshed = results[1] if len(results) > 1 else 0

            if counter_refreshed == 0:
                logger.warning(
                    "Heartbeat: counter key missing or expired",
                    extra={
                        "job_id": str(self._job_id),
                        "concurrency_key": concurrency_key,
                    },
                )
            if flag_refreshed == 0:
                logger.warning(
                    "Heartbeat: flag key missing or expired",
                    extra={
                        "job_id": str(self._job_id),
                        "flag_key": flag_key,
                    },
                )

        except Exception:
            self._consecutive_failures += 1
            logger.warning(
                "Heartbeat Redis pipeline failed",
                extra={
                    "consecutive_failures": self._consecutive_failures,
                    "max_failures": self._max_failures,
                    "job_id": str(self._job_id),
                },
            )

            if self._consecutive_failures >= self._max_failures:
                logger.error(
                    "Terminating crawl: heartbeat failures exceeded threshold",
                    extra={
                        "consecutive_failures": self._consecutive_failures,
                        "max_failures": self._max_failures,
                        "job_id": str(self._job_id),
                    },
                )
                raise HeartbeatFailedError(
                    self._consecutive_failures, self._max_failures
                )

    async def _check_preemption(self) -> None:
        """Check if job was externally preempted (marked as FAILED).

        Uses a short-lived session to avoid holding connections.

        Raises:
            JobPreemptedError: If job status is FAILED
        """
        try:
            from intric.database.database import sessionmanager
            from intric.jobs.job_repo import JobRepository
            from intric.main.models import Status as JobStatus

            async with sessionmanager.session() as session:
                async with session.begin():
                    job_repo = JobRepository(session=session)
                    job = await job_repo.get_job(self._job_id)

                    if job and job.status == JobStatus.FAILED:
                        logger.warning(
                            "Detected job preemption during heartbeat",
                            extra={"job_id": str(self._job_id)},
                        )
                        raise JobPreemptedError(self._job_id)

        except JobPreemptedError:
            raise
        except Exception as exc:
            logger.warning(
                f"Preemption check failed: {exc}",
                extra={"job_id": str(self._job_id)},
            )
