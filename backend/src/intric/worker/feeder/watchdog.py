"""Orphan job cleanup with Safe Watchdog pattern.

Provides 5-phase cleanup for stuck/orphaned crawl jobs:
- Phase 0: Zombie counter reconciliation (Redis vs DB)
- Phase 1: Kill expired QUEUED jobs (created_at > max_age)
- Phase 2: Rescue stuck QUEUED jobs (stale updated_at, fresh created_at)
- Phase 3.5: Fail stalled startup jobs (IN_PROGRESS + no progress + stale, ~15min)
- Phase 3: Fail long-running IN_PROGRESS jobs (12h timeout for jobs WITH progress)

Phase 3.5 vs Phase 3:
- Phase 3.5 catches "early zombies" - workers that crashed before any progress.
  Uses compound condition: IN_PROGRESS + pages_crawled IS NULL/0 + updated_at stale.
  Timeout aligned with heartbeat config (5min × 3 failures = 15min).
- Phase 3 catches jobs that made progress but ran too long (>12h).
  Protects legitimate large crawls that can take up to 10 hours.

Transaction safety: All DB operations happen inside a transaction.
Slot releases happen AFTER commit (best-effort, won't rollback DB).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from intric.main.logging import get_logger
from intric.worker.redis.lua_scripts import LuaScripts

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass
class SlotReleaseJob:
    """Job requiring slot release after transaction commit."""

    job_id: UUID
    tenant_id: UUID


@dataclass
class Phase1Result:
    """Result of Phase 1: Kill expired jobs."""

    expired_job_ids: list[UUID] = field(default_factory=list)
    slots_to_release: list[SlotReleaseJob] = field(default_factory=list)
    orphaned_job_ids: list[UUID] = field(default_factory=list)


@dataclass
class Phase2Result:
    """Result of Phase 2: Rescue stuck jobs."""

    jobs_to_requeue: list[dict] = field(default_factory=list)
    rescued_count: int = 0


@dataclass
class Phase3Result:
    """Result of Phase 3: Fail long-running jobs."""

    failed_job_ids: list[UUID] = field(default_factory=list)
    slots_to_release: list[SlotReleaseJob] = field(default_factory=list)


@dataclass
class Phase3_5Result:
    """Result of Phase 3.5: Fail stalled startup jobs (early zombies).

    Detects jobs that are IN_PROGRESS but never made progress:
    - pages_crawled IS NULL (no progress persisted)
    - updated_at stale (no heartbeat within threshold)

    These are "early zombies" - workers that crashed before processing any pages.
    Uses shorter timeout than Phase 3 to avoid blocking users for 12 hours.
    """

    failed_job_ids: list[UUID] = field(default_factory=list)
    slots_to_release: list[SlotReleaseJob] = field(default_factory=list)


@dataclass
class CleanupMetrics:
    """Metrics from a watchdog cleanup run."""

    zombies_reconciled: int = 0
    expired_killed: int = 0
    rescued: int = 0
    early_zombies_failed: int = 0  # Phase 3.5: stalled startup jobs
    long_running_failed: int = 0
    slots_released: int = 0


class OrphanWatchdog:
    """Cleans up orphaned crawl jobs with transaction-safe slot release.

    Uses "Collector Pattern": phases return jobs needing slot release,
    actual Redis operations happen AFTER DB transaction commits.

    Args:
        redis_client: Async Redis connection.
        settings: Application settings with timeout thresholds.
    """

    def __init__(self, redis_client: aioredis.Redis, settings) -> None:
        self._redis = redis_client
        self._settings = settings

    async def run_cleanup(self) -> CleanupMetrics:
        """Execute all cleanup phases with transaction-safe orchestration.

        Returns:
            Metrics from the cleanup run.
        """
        from intric.database.database import sessionmanager

        metrics = CleanupMetrics()
        slots_to_release: list[SlotReleaseJob] = []

        now = datetime.now(timezone.utc)

        try:
            async with sessionmanager.session() as session, session.begin():
                # Phase 0: Zombie counter reconciliation (can be Redis-only)
                phase0_result = await self._run_phase0_reconciliation(session)
                metrics.zombies_reconciled = phase0_result.get("reconciled_count", 0)

                # Phase 1: Kill expired QUEUED jobs
                phase1_result = await self._kill_expired_jobs(session, now=now)
                metrics.expired_killed = len(phase1_result.expired_job_ids)
                slots_to_release.extend(phase1_result.slots_to_release)

                # Phase 2: Rescue stuck QUEUED jobs
                phase2_result = await self._rescue_stuck_jobs(session, now=now)
                metrics.rescued = phase2_result.rescued_count

                # Phase 3.5: Fail stalled startup jobs (early zombies)
                # Runs BEFORE Phase 3 to catch jobs that never made progress
                phase3_5_result = await self._fail_stalled_startup_jobs(
                    session, now=now
                )
                metrics.early_zombies_failed = len(phase3_5_result.failed_job_ids)
                slots_to_release.extend(phase3_5_result.slots_to_release)

                # Phase 3: Fail long-running IN_PROGRESS jobs (with progress)
                phase3_result = await self._fail_long_running_jobs(session, now=now)
                metrics.long_running_failed = len(phase3_result.failed_job_ids)
                slots_to_release.extend(phase3_result.slots_to_release)

                # Transaction auto-commits on exit

            # Post-transaction: Release slots (best effort)
            if slots_to_release:
                metrics.slots_released = await self._release_slots_safe(
                    slots_to_release
                )

            # Record successful cleanup timestamp for observability
            # TTL = max(2 * feeder cadence, 300s) to avoid flapping if feeder
            # has backoff; monitoring can alert on key absence to detect dead watchdog
            watchdog_ttl = max(
                2 * self._settings.crawl_feeder_interval_seconds,
                300,  # minimum 5 minutes
            )
            try:
                await self._redis.set(
                    "crawl_watchdog:last_success_epoch",
                    str(int(now.timestamp())),
                    ex=watchdog_ttl,
                )
            except Exception as redis_exc:
                logger.debug(
                    "Failed to update watchdog success timestamp",
                    extra={"error": str(redis_exc)},
                )

            self._log_metrics(metrics)

        except Exception as exc:
            logger.warning(
                "Failed to run Safe Watchdog cleanup",
                extra={"error": str(exc)},
            )

        return metrics

    async def _run_phase0_reconciliation(self, session: AsyncSession) -> dict:
        """Phase 0: Detect and fix zombie counters.

        Scans Redis for tenant active_jobs counters that exceed actual
        DB active job counts. Uses CAS to prevent race conditions.

        Args:
            session: Database session for querying active jobs.

        Returns:
            Dict with reconciliation stats.
        """
        from sqlalchemy import func, select

        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns
        from intric.main.models import Status

        reconciled_count = 0

        try:
            async for key in self._redis.scan_iter(match="tenant:*:active_jobs"):
                try:
                    result = await self._reconcile_single_counter(
                        session, key, Jobs, CrawlRuns, Status, func, select
                    )
                    if result.get("reconciled"):
                        reconciled_count += 1
                except Exception as key_exc:
                    logger.debug(
                        "Phase 0 reconciliation error for key",
                        extra={"key": str(key), "error": str(key_exc)},
                    )
                    continue

            if reconciled_count > 0:
                logger.info(
                    f"Phase 0: Reconciled {reconciled_count} zombie counters",
                    extra={"reconciled_count": reconciled_count},
                )

        except Exception as phase0_exc:
            logger.warning(
                "Phase 0 reconciliation failed",
                extra={"error": str(phase0_exc)},
            )

        return {"reconciled_count": reconciled_count}

    async def _reconcile_single_counter(
        self,
        session: AsyncSession,
        key: bytes,
        Jobs,
        CrawlRuns,
        Status,
        func,
        select,
    ) -> dict:
        """Reconcile a single tenant's zombie counter."""
        key_str = key.decode("utf-8") if isinstance(key, bytes) else key
        parts = key_str.split(":")
        if len(parts) != 3:
            return {"reconciled": False}

        tenant_id_str = parts[1]

        try:
            tenant_uuid = UUID(tenant_id_str)
        except ValueError:
            return {"reconciled": False}

        redis_val = await self._redis.get(key)
        if not redis_val:
            return {"reconciled": False}

        redis_count = int(
            redis_val.decode() if isinstance(redis_val, bytes) else redis_val
        )

        if redis_count <= 0:
            return {"reconciled": False}

        # Query actual active jobs in DB
        actual_active = await session.scalar(
            select(func.count())
            .select_from(Jobs)
            .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
            .where(
                Jobs.task == "CRAWL",
                Jobs.status.in_([Status.QUEUED, Status.IN_PROGRESS]),
                CrawlRuns.tenant_id == tenant_uuid,
            )
        )

        if redis_count <= actual_active:
            return {"reconciled": False}

        # CAS reconciliation
        ttl = self._settings.tenant_worker_semaphore_ttl_seconds
        result_str = await LuaScripts.reconcile_counter(
            self._redis, tenant_uuid, redis_count, actual_active, ttl
        )

        if result_str.startswith("ok:"):
            logger.warning(
                "Zombie counter reconciled",
                extra={
                    "tenant_id": tenant_id_str,
                    "redis_count": redis_count,
                    "actual_active": actual_active,
                    "released": redis_count - actual_active,
                },
            )
            return {"reconciled": True}

        if result_str.startswith("mismatch:"):
            return {"reconciled": False, "skipped_reason": "cas_mismatch"}

        return {"reconciled": False}

    async def _reconcile_zombie_counters(
        self,
        session: AsyncSession,
        db_active_count: int,
        tenant_id: UUID,
        redis_count: int | None = None,
    ) -> dict:
        """Reconcile zombie counter for a specific tenant (for testing).

        Args:
            session: Database session.
            db_active_count: Actual active job count from DB.
            tenant_id: Tenant identifier.
            redis_count: Redis counter value (optional, fetched if not provided).

        Returns:
            Dict with reconciliation result.
        """
        if redis_count is None:
            key = f"tenant:{tenant_id}:active_jobs"
            redis_val = await self._redis.get(key)
            if not redis_val:
                return {"reconciled": False}
            redis_count = int(
                redis_val.decode() if isinstance(redis_val, bytes) else redis_val
            )

        if redis_count <= db_active_count:
            return {"reconciled": False}

        ttl = self._settings.tenant_worker_semaphore_ttl_seconds
        result_str = await LuaScripts.reconcile_counter(
            self._redis, tenant_id, redis_count, db_active_count, ttl
        )

        if result_str.startswith("ok:"):
            return {"reconciled": True}

        if result_str.startswith("mismatch:"):
            return {"reconciled": False, "skipped_reason": "cas_mismatch"}

        return {"reconciled": False}

    async def _kill_expired_jobs(
        self, session: AsyncSession, now: datetime
    ) -> Phase1Result:
        """Phase 1: Mark expired QUEUED jobs as FAILED.

        Jobs where created_at exceeds max_age are permanently failed.
        Uses created_at (immutable) to prevent infinite re-queue loops.

        Args:
            session: Database session.
            now: Current timestamp.

        Returns:
            Phase1Result with jobs to release slots for.
        """
        from sqlalchemy import and_, select, update

        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns
        from intric.main.models import Status

        max_age_seconds = self._settings.crawl_job_max_age_seconds or 7200
        max_age_cutoff = now - timedelta(seconds=max_age_seconds)

        result = Phase1Result()

        # Get all expired job IDs (including orphaned without CrawlRun)
        all_expired_query = select(Jobs.id).where(
            and_(
                Jobs.task == "CRAWL",
                Jobs.status == Status.QUEUED,
                Jobs.created_at < max_age_cutoff,
            )
        )
        all_expired_result = await session.execute(all_expired_query)
        all_expired_ids = {row.id for row in all_expired_result.fetchall()}

        # Get expired jobs WITH CrawlRuns (need tenant_id for slot release)
        expired_with_tenant_query = (
            select(Jobs.id.label("job_id"), CrawlRuns.tenant_id)
            .select_from(Jobs)
            .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
            .where(
                and_(
                    Jobs.task == "CRAWL",
                    Jobs.status == Status.QUEUED,
                    Jobs.created_at < max_age_cutoff,
                )
            )
        )
        expired_result = await session.execute(expired_with_tenant_query)
        expired_rows = expired_result.fetchall()

        # Track jobs for slot release
        jobs_with_crawlrun = set()
        for row in expired_rows:
            result.expired_job_ids.append(row.job_id)
            result.slots_to_release.append(
                SlotReleaseJob(job_id=row.job_id, tenant_id=row.tenant_id)
            )
            jobs_with_crawlrun.add(row.job_id)

        # Identify orphaned jobs (no CrawlRun)
        result.orphaned_job_ids = list(all_expired_ids - jobs_with_crawlrun)

        # Mark all expired jobs as FAILED
        if all_expired_ids:
            kill_stmt = (
                update(Jobs)
                .where(
                    and_(
                        Jobs.task == "CRAWL",
                        Jobs.status == Status.QUEUED,
                        Jobs.created_at < max_age_cutoff,
                    )
                )
                .values(status=Status.FAILED, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await session.execute(kill_stmt)

            # Log Phase 1 metrics for observability
            logger.info(
                "Phase 1: Killed expired QUEUED jobs",
                extra={
                    "selected_count": len(all_expired_ids),
                    "with_crawlrun_count": len(jobs_with_crawlrun),
                    "orphaned_count": len(result.orphaned_job_ids),
                    "max_age_seconds": max_age_seconds,
                },
            )

        return result

    async def _rescue_stuck_jobs(
        self,
        session: AsyncSession,
        now: datetime,
        stale_threshold_minutes: int = 5,
    ) -> Phase2Result:
        """Phase 2: Re-queue stuck QUEUED jobs with per-tenant thresholds.

        Jobs with stale updated_at but fresh created_at are re-queued.
        updated_at is bumped to prevent immediate re-pickup.

        Per-tenant thresholds:
        - Uses queued_stale_threshold_minutes from tenant's crawler_settings
        - Safety bounds: floor=5 min, ceiling=60 min
        - Fallback to default (5 min) if unset

        Args:
            session: Database session.
            now: Current timestamp.
            stale_threshold_minutes: Default threshold (used as fallback).

        Returns:
            Phase2Result with jobs to requeue.
        """
        from sqlalchemy import and_, select, update

        from intric.database.tables.job_table import Jobs
        from intric.database.tables.tenant_table import Tenants
        from intric.database.tables.websites_table import CrawlRuns, Websites
        from intric.main.models import Status
        from intric.tenants.crawler_settings_helper import get_crawler_setting

        # Safety bounds for threshold (per plan: floor=5, ceiling=60)
        THRESHOLD_FLOOR_MINUTES = 5
        THRESHOLD_CEILING_MINUTES = 60

        max_age_seconds = self._settings.crawl_job_max_age_seconds or 7200
        max_age_cutoff = now - timedelta(seconds=max_age_seconds)

        # Use floor threshold as SQL cutoff to reduce query load
        # No tenant can have a threshold below the floor, so we won't miss valid rescues
        min_stale_cutoff = now - timedelta(minutes=THRESHOLD_FLOOR_MINUTES)

        result = Phase2Result()

        # Find potentially stuck jobs (stale but not expired), including tenant settings
        rescue_query = (
            select(
                Jobs.id.label("job_id"),
                Jobs.user_id,
                Jobs.updated_at,
                CrawlRuns.id.label("run_id"),
                CrawlRuns.tenant_id,
                CrawlRuns.website_id,
                Websites.url,
                Websites.download_files,
                Websites.crawl_type,
                Tenants.crawler_settings,
            )
            .select_from(Jobs)
            .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
            .join(Websites, Websites.id == CrawlRuns.website_id)
            .join(Tenants, Tenants.id == CrawlRuns.tenant_id)
            .where(
                and_(
                    Jobs.task == "CRAWL",
                    Jobs.status == Status.QUEUED,
                    Jobs.updated_at < min_stale_cutoff,
                    Jobs.created_at >= max_age_cutoff,
                )
            )
        )
        rescue_result = await session.execute(rescue_query)
        potential_stuck_jobs = rescue_result.fetchall()

        # Re-queue stuck jobs that meet their tenant's threshold
        rescued_job_ids = []
        skipped_count = 0
        for row in potential_stuck_jobs:
            # Get tenant-specific threshold with bounds
            raw_threshold = get_crawler_setting(
                "queued_stale_threshold_minutes",
                row.crawler_settings,
                default=stale_threshold_minutes,
            )
            # Apply safety bounds
            effective_threshold = max(
                THRESHOLD_FLOOR_MINUTES,
                min(THRESHOLD_CEILING_MINUTES, raw_threshold),
            )

            # Check if job is stale according to this tenant's threshold
            tenant_stale_cutoff = now - timedelta(minutes=effective_threshold)
            if row.updated_at >= tenant_stale_cutoff:
                # Job is not stale enough for this tenant's threshold
                skipped_count += 1
                continue

            try:
                await self._requeue_job(
                    job_id=row.job_id,
                    user_id=row.user_id,
                    run_id=row.run_id,
                    tenant_id=row.tenant_id,
                    website_id=row.website_id,
                    url=row.url,
                    download_files=row.download_files,
                    crawl_type=row.crawl_type,
                )
                result.jobs_to_requeue.append({"job_id": row.job_id})
                rescued_job_ids.append(row.job_id)
                result.rescued_count += 1
            except Exception as requeue_exc:
                logger.warning(
                    "Failed to re-queue stuck job",
                    extra={"job_id": str(row.job_id), "error": str(requeue_exc)},
                )

        # Bump updated_at for rescued jobs (visibility timeout)
        if rescued_job_ids:
            bump_stmt = (
                update(Jobs)
                .where(Jobs.id.in_(rescued_job_ids))
                .values(updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await session.execute(bump_stmt)

        # Log Phase 2 metrics for observability
        if potential_stuck_jobs:
            logger.info(
                "Phase 2: Rescued stuck QUEUED jobs",
                extra={
                    "selected_count": len(potential_stuck_jobs),
                    "rescued_count": result.rescued_count,
                    "skipped_by_threshold": skipped_count,
                    "default_threshold_minutes": stale_threshold_minutes,
                },
            )

        return result

    async def _requeue_job(
        self,
        job_id: UUID,
        user_id: UUID,
        run_id: UUID,
        tenant_id: UUID,
        website_id: UUID,
        url: str,
        download_files: bool,
        crawl_type: str,
    ) -> bool:
        """Re-queue a stuck job to ARQ.

        Uses ARQ's native enqueue with job_id for deduplication.

        Returns:
            True if job was re-queued, False if skipped.
        """
        from arq.jobs import Job, JobStatus

        from intric.jobs.job_manager import job_manager
        from intric.jobs.job_models import Task
        from intric.websites.crawl_dependencies.crawl_models import CrawlTask, CrawlType

        # Check ARQ status first
        arq_job = Job(job_id=str(job_id), redis=self._redis)
        try:
            status = await arq_job.status()
        except Exception:
            status = JobStatus.not_found

        if status != JobStatus.not_found:
            logger.info(
                "Job already in ARQ, skipping re-queue",
                extra={"job_id": str(job_id), "arq_status": status.value},
            )
            return False

        params = CrawlTask(
            user_id=user_id,
            website_id=website_id,
            run_id=run_id,
            url=url,
            download_files=download_files,
            crawl_type=CrawlType(crawl_type)
            if isinstance(crawl_type, str)
            else crawl_type,
        )

        try:
            await job_manager.enqueue(task=Task.CRAWL, job_id=job_id, params=params)
            logger.info(
                "Re-queued stuck job to ARQ",
                extra={"job_id": str(job_id), "tenant_id": str(tenant_id)},
            )
            return True
        except Exception as exc:
            error_msg = str(exc).lower()
            if "already exists" in error_msg or "duplicate" in error_msg:
                return True
            raise

    async def _fail_stalled_startup_jobs(
        self, session: AsyncSession, now: datetime
    ) -> Phase3_5Result:
        """Phase 3.5: Fail early zombie jobs that never made progress.

        Detects jobs that are IN_PROGRESS but have:
        - pages_crawled IS NULL (no progress persisted to CrawlRun)
        - updated_at stale beyond startup threshold

        These are "early zombies" - workers crashed after _on_job_start hook
        marked the job IN_PROGRESS, but before any actual crawling began.

        Uses compound condition to avoid false positives:
        - Legitimate slow-starting crawls will have heartbeat updating updated_at
        - Threshold aligned with heartbeat config (5min × 3 failures = 15min)

        Args:
            session: Database session.
            now: Current timestamp.

        Returns:
            Phase3_5Result with jobs to release slots for.
        """
        from sqlalchemy import and_, or_, select, update

        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns
        from intric.main.models import Status

        # Use heartbeat-aligned threshold: 3 × heartbeat_interval = ~15 minutes
        # This aligns with crawl_heartbeat_max_failures × crawl_heartbeat_interval_seconds
        heartbeat_interval = self._settings.crawl_heartbeat_interval_seconds
        max_failures = self._settings.crawl_heartbeat_max_failures
        startup_timeout_seconds = heartbeat_interval * max_failures  # 5min × 3 = 15min

        startup_cutoff = now - timedelta(seconds=startup_timeout_seconds)

        result = Phase3_5Result()

        # Find early zombie jobs: IN_PROGRESS with no progress and stale updated_at
        # Catch both NULL and 0 for pages_crawled (some code paths may initialize to 0)
        query = (
            select(
                Jobs.id.label("job_id"),
                CrawlRuns.tenant_id,
                CrawlRuns.id.label("crawl_run_id"),
            )
            .select_from(Jobs)
            .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
            .where(
                and_(
                    Jobs.task == "CRAWL",
                    Jobs.status == Status.IN_PROGRESS,
                    Jobs.updated_at < startup_cutoff,
                    # Compound condition: no progress ever made (NULL or 0)
                    or_(
                        CrawlRuns.pages_crawled.is_(None), CrawlRuns.pages_crawled == 0
                    ),
                )
            )
        )
        query_result = await session.execute(query)
        stalled_jobs = query_result.fetchall()

        if stalled_jobs:
            stalled_job_ids = [row.job_id for row in stalled_jobs]

            logger.info(
                "Phase 3.5: Found stalled startup jobs (early zombies)",
                extra={
                    "count": len(stalled_job_ids),
                    "startup_timeout_seconds": startup_timeout_seconds,
                    "job_ids": [str(jid) for jid in stalled_job_ids[:5]],  # Log first 5
                },
            )

            # Mark as FAILED
            fail_stmt = (
                update(Jobs)
                .where(Jobs.id.in_(stalled_job_ids))
                .values(status=Status.FAILED, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await session.execute(fail_stmt)

            # Track for slot release
            for row in stalled_jobs:
                result.failed_job_ids.append(row.job_id)
                result.slots_to_release.append(
                    SlotReleaseJob(job_id=row.job_id, tenant_id=row.tenant_id)
                )

        return result

    async def _fail_long_running_jobs(
        self, session: AsyncSession, now: datetime
    ) -> Phase3Result:
        """Phase 3: Mark long-running IN_PROGRESS jobs as FAILED.

        Jobs in IN_PROGRESS status exceeding timeout are failed.
        Their slots need to be released.

        Args:
            session: Database session.
            now: Current timestamp.

        Returns:
            Phase3Result with jobs to release slots for.
        """
        from sqlalchemy import and_, select, update

        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns
        from intric.main.models import Status

        timeout_hours = self._settings.orphan_crawl_run_timeout_hours
        timeout_cutoff = now - timedelta(hours=timeout_hours)

        result = Phase3Result()

        # Find long-running jobs
        query = (
            select(Jobs.id.label("job_id"), CrawlRuns.tenant_id)
            .select_from(Jobs)
            .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
            .where(
                and_(
                    Jobs.task == "CRAWL",
                    Jobs.status == Status.IN_PROGRESS,
                    Jobs.updated_at < timeout_cutoff,
                )
            )
        )
        query_result = await session.execute(query)
        stale_jobs = query_result.fetchall()

        if stale_jobs:
            stale_job_ids = [row.job_id for row in stale_jobs]

            # Mark as FAILED
            fail_stmt = (
                update(Jobs)
                .where(Jobs.id.in_(stale_job_ids))
                .values(status=Status.FAILED, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            await session.execute(fail_stmt)

            # Track for slot release
            for row in stale_jobs:
                result.failed_job_ids.append(row.job_id)
                result.slots_to_release.append(
                    SlotReleaseJob(job_id=row.job_id, tenant_id=row.tenant_id)
                )

        return result

    async def _release_slots_safe(self, slots: list[SlotReleaseJob]) -> int:
        """Release slots for jobs (best effort, post-transaction).

        Only releases if the pre-acquired flag exists (job had a slot).

        Args:
            slots: Jobs needing slot release.

        Returns:
            Number of slots successfully released.
        """
        released = 0
        ttl = self._settings.tenant_worker_semaphore_ttl_seconds

        for slot in slots:
            flag_key = f"job:{slot.job_id}:slot_preacquired"
            try:
                if await self._redis.get(flag_key):
                    await LuaScripts.release_slot(self._redis, slot.tenant_id, ttl)
                    await self._redis.delete(flag_key)
                    released += 1
                    logger.debug(
                        "Released slot for job",
                        extra={
                            "job_id": str(slot.job_id),
                            "tenant_id": str(slot.tenant_id),
                        },
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to release slot for job",
                    extra={
                        "job_id": str(slot.job_id),
                        "tenant_id": str(slot.tenant_id),
                        "error": str(exc),
                    },
                )

        if released > 0:
            logger.info(
                f"Safe Watchdog released {released} slots",
                extra={"released": released, "total": len(slots)},
            )

        return released

    def _log_metrics(self, metrics: CleanupMetrics) -> None:
        """Log cleanup metrics if any work was done."""
        if (
            metrics.zombies_reconciled > 0
            or metrics.expired_killed > 0
            or metrics.rescued > 0
            or metrics.early_zombies_failed > 0
            or metrics.long_running_failed > 0
        ):
            logger.info(
                f"Safe Watchdog: zombies={metrics.zombies_reconciled}, "
                f"killed={metrics.expired_killed}, rescued={metrics.rescued}, "
                f"early_zombies={metrics.early_zombies_failed}, "
                f"failed_in_progress={metrics.long_running_failed}",
                extra={
                    "zombies_reconciled": metrics.zombies_reconciled,
                    "expired_killed": metrics.expired_killed,
                    "rescued": metrics.rescued,
                    "early_zombies_failed": metrics.early_zombies_failed,
                    "long_running_failed": metrics.long_running_failed,
                    "slots_released": metrics.slots_released,
                },
            )
