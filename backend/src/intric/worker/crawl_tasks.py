import hashlib
import random
import socket
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from arq import Retry
from dependency_injector import providers
import redis.asyncio as aioredis
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.ai_models.model_enums import ModelFamily
from intric.main.container.container import Container
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.worker.crawl import (
    HeartbeatFailedError,
    HeartbeatMonitor,
    JobPreemptedError,
    persist_batch,
    execute_with_recovery,
    reset_tenant_retry_delay,
    update_job_retry_stats,
)
from intric.worker.crawl_context import CrawlContext, EmbeddingModelSpec
from intric.worker.feeder.capacity import CapacityManager
from intric.worker.feeder.election import LeaderElection
from intric.worker.feeder.queues import PendingQueue
from intric.worker.redis.lua_scripts import LuaScripts
from intric.worker.task_manager import TaskManager
from intric.websites.crawl_dependencies.crawl_models import CrawlTask

logger = get_logger(__name__)

SCHEDULER_LOCK_KEY = "crawl_scheduler:leader"
SCHEDULER_LOCK_TTL_SECONDS = 1800


async def _get_primary_active_job_id(
    session: AsyncSession,
    *,
    website_id: UUID,
) -> UUID | None:
    """Return the oldest active crawl job ID for a website.

    Used to ensure newer duplicate crawl jobs yield to the earliest queued or
    running job, preventing duplicate executions when schedules overlap.
    """
    from intric.database.tables.job_table import Jobs
    from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
    from intric.main.models import Status

    active_statuses = [Status.QUEUED.value, Status.IN_PROGRESS.value]
    stmt = (
        sa.select(Jobs.id)
        .join(CrawlRunsTable, CrawlRunsTable.job_id == Jobs.id)
        .where(CrawlRunsTable.website_id == website_id)
        .where(Jobs.status.in_(active_statuses))
        .order_by(Jobs.created_at.asc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def queue_website_crawls(container: Container):
    """Queue websites for crawling based on their update intervals.

    Why: Uses centralized scheduler service for maintainable interval logic.
    Properly handles DAILY, EVERY_OTHER_DAY, and WEEKLY intervals.

    Phase 2 Enhancement: When feeder is enabled, adds to pending queue instead
    of direct ARQ enqueue to prevent burst overload.

    Session Strategy (P0 FIX): Uses SHORT-LIVED sessions for each operation to
    prevent connection pool exhaustion. Previously held one session for the
    entire loop (60+ seconds), causing QueuePool limit reached errors.

    Now:
    - Phase 1: Query websites → release connection immediately
    - Phase 2: Each website gets its own session → release after each
    """
    from intric.database.database import sessionmanager

    settings = get_settings()

    scheduler_lock = None
    scheduler_lock_acquired = False
    scheduler_worker_id = socket.gethostname()

    try:
        redis_client = container.redis_client()
    except Exception as exc:
        redis_client = None
        logger.warning(
            "Failed to initialize Redis client for crawl scheduling",
            extra={"error": str(exc)},
        )

    # Scheduler lock: prevent multiple workers from enqueueing the same schedule
    if redis_client:
        scheduler_lock = LeaderElection(
            redis_client,
            scheduler_worker_id,
            lock_key=SCHEDULER_LOCK_KEY,
            ttl_seconds=SCHEDULER_LOCK_TTL_SECONDS,
        )
        scheduler_lock_acquired = await scheduler_lock.try_acquire()
        if not scheduler_lock_acquired:
            logger.info(
                "Skipping crawl scheduling; another worker holds the scheduler lock",
                extra={
                    "lock_key": SCHEDULER_LOCK_KEY,
                    "lock_ttl_seconds": SCHEDULER_LOCK_TTL_SECONDS,
                    "worker_id": scheduler_worker_id,
                },
            )
            return False
        logger.debug(
            "Acquired crawl scheduler lock",
            extra={
                "lock_key": SCHEDULER_LOCK_KEY,
                "lock_ttl_seconds": SCHEDULER_LOCK_TTL_SECONDS,
                "worker_id": scheduler_worker_id,
            },
        )

    # Get Redis client for feeder mode (if enabled)
    if settings.crawl_feeder_enabled and redis_client is None:
        logger.error(
            "Feeder enabled but Redis unavailable; falling back to direct enqueue mode."
        )

    try:
        # PHASE 1: Query due websites with SHORT-LIVED session (~50-200ms)
        # Release connection immediately after query completes to prevent
        # "Connection held for 60s" warnings when processing many websites.
        async with sessionmanager.session() as query_session, query_session.begin():
            crawl_scheduler_service = container.crawl_scheduler_service()
            # Inject the short-lived session for this query only
            crawl_scheduler_service.website_sparse_repo.session = query_session
            websites = await crawl_scheduler_service.get_websites_due_for_crawl()
        # Session is now CLOSED - connection returned to pool

        logger.info(
            f"Processing {len(websites)} websites due for crawling",
            extra={
                "feeder_enabled": settings.crawl_feeder_enabled,
                "mode": "pending_queue"
                if settings.crawl_feeder_enabled
                else "direct_enqueue",
                "website_count": len(websites),
            },
        )

        successful_crawls = 0
        failed_crawls = 0

        # PHASE 2: Process each website with its OWN short-lived session
        # Each website operation takes ~100-500ms. Without per-website sessions,
        # 100 websites would hold ONE connection for 10-50 seconds.
        # With per-website sessions, each connection is held for <500ms.
        for website in websites:
            try:
                # Each website gets its own session scope
                async with (
                    sessionmanager.session() as website_session,
                    website_session.begin(),
                ):
                    # Create repos with this session
                    user_repo = container.user_repo()
                    user_repo.session = website_session

                    # Get user for this website
                    user = await user_repo.get_user_by_id(website.user_id)
                    container.user.override(providers.Object(user))
                    container.tenant.override(providers.Object(user.tenant))

                    # Feeder mode: Create crawl run AND job record, then add to pending queue
                    # Why: Pre-create DB records so feeder only handles ARQ enqueueing
                    # Deterministic job_id based on run_id prevents duplicate enqueues
                    if settings.crawl_feeder_enabled and redis_client:
                        from intric.websites.domain.crawl_run import CrawlRun
                        from intric.jobs.job_models import Job, Task
                        from intric.main.models import Status

                        # Step 1: Create crawl run record
                        crawl_run_repo = container.crawl_run_repo()
                        crawl_run_repo.session = website_session
                        crawl_run = CrawlRun.create(website=website)
                        crawl_run = await crawl_run_repo.add(crawl_run=crawl_run)

                        # Step 2: Create job record in database
                        # Why: Pre-create so job_id is deterministic and available for feeder
                        # CRITICAL: Use website_session, not container's outer cron_job session!
                        # Bug fix: Job and CrawlRun must commit together for watchdog JOIN to work.
                        # See: watchdog.py zombie reconciliation query joins Jobs with CrawlRuns
                        job_repo = container.job_repo()
                        job_repo.delegate.session = (
                            website_session  # Align with crawl_run_repo
                        )
                        job = Job(
                            task=Task.CRAWL,
                            name=f"Crawl: {website.name or website.url}",
                            status=Status.QUEUED,
                            user_id=website.user_id,
                        )
                        job_in_db = await job_repo.add_job(job=job)

                        # Step 3: Link job_id to crawl_run
                        crawl_run.update(job_id=job_in_db.id)
                        await crawl_run_repo.update(crawl_run=crawl_run)

                        # Step 4: Prepare job data for pending queue
                        # Store database job_id for deterministic enqueueing
                        job_data = {
                            "job_id": str(
                                job_in_db.id
                            ),  # Critical: Deterministic ID from DB
                            "user_id": str(website.user_id),
                            "website_id": str(website.id),
                            "run_id": str(crawl_run.id),
                            "url": website.url,
                            "download_files": website.download_files,
                            "crawl_type": website.crawl_type.value,
                        }

                        # Step 5: Add to pending queue with orphaning protection
                        # If Redis push fails, mark DB records as FAILED
                        # Why: Prevents orphaned crawl_run/job records that never execute
                        try:
                            pending_queue = PendingQueue(redis_client)
                            if not await pending_queue.add(
                                tenant_id=user.tenant.id,
                                job_data=job_data,
                            ):
                                raise Exception("Failed to add to pending queue")

                            successful_crawls += 1
                            logger.debug(
                                f"Added crawl to pending queue: {website.url}",
                                extra={
                                    "feeder_mode": True,
                                    "job_id": str(job_in_db.id),
                                    "run_id": str(crawl_run.id),
                                },
                            )
                        except Exception as redis_exc:
                            # Redis push failed, rollback by marking DB records as FAILED
                            # Why: Prevents silent data loss and orphaned records
                            try:
                                from intric.main.models import Status

                                job_in_db.status = Status.FAILED
                                await job_repo.update_job(job_in_db)

                                crawl_run.status = Status.FAILED
                                await crawl_run_repo.update(crawl_run)
                            except Exception as update_exc:
                                logger.warning(
                                    "Failed to rollback DB records after Redis error",
                                    extra={
                                        "job_id": str(job_in_db.id),
                                        "error": str(update_exc),
                                    },
                                )

                            failed_crawls += 1
                            logger.error(
                                f"Failed to add to pending queue: {redis_exc}",
                                extra={
                                    "website_id": str(website.id),
                                    "url": website.url,
                                    "job_id": str(job_in_db.id),
                                },
                            )
                    else:
                        # Direct enqueue mode (original behavior when feeder disabled)
                        crawl_service = container.crawl_service()
                        await crawl_service.crawl(website)
                        successful_crawls += 1

                        logger.debug(f"Successfully queued crawl for {website.url}")

                # Session is now CLOSED for this website - connection returned to pool

            except Exception as e:
                # Why: Individual website failures shouldn't stop the entire batch
                failed_crawls += 1
                logger.error(
                    f"Failed to queue crawl for {website.url}: {str(e)}",
                    extra={
                        "website_id": str(website.id),
                        "tenant_id": str(website.tenant_id),
                        "space_id": str(website.space_id),
                        "user_id": str(website.user_id),
                    },
                )
                continue

        logger.info(
            f"Crawl queueing completed: {successful_crawls} successful, {failed_crawls} failed"
        )

        return True
    finally:
        if scheduler_lock and scheduler_lock_acquired:
            released = await scheduler_lock.release()
            if not released:
                logger.debug(
                    "Failed to release crawl scheduler lock",
                    extra={
                        "lock_key": SCHEDULER_LOCK_KEY,
                        "worker_id": scheduler_worker_id,
                    },
                )


async def crawl_task(*, job_id: UUID, params: CrawlTask, container: Container):
    # Normalize job_id - ARQ passes job_id as string in ctx
    job_id = job_id if isinstance(job_id, UUID) else UUID(str(job_id))
    # Create TaskManager directly without using container.task_manager()
    # Why: container.task_manager() tries to resolve job_service which has
    # transitive dependency: job_service → job_repo → session
    # With sessionless container (session=None), this fails type validation.
    #
    # This is safe because:
    # 1. crawl_task sets _job_already_handled=True, skipping complete_job/fail_job
    # 2. Status updates use execute_with_recovery() with its own sessions
    # 3. set_status() has fallback to direct SQL when job_service is None
    task_manager = TaskManager(
        user=container.user(),
        job_id=job_id,
        job_service=None,  # Not needed for crawl_task - status handled via execute_with_recovery
    )
    settings = get_settings()

    tenant = None
    limiter = None
    acquired = False
    redis_client: aioredis.Redis | None = None
    # Track pre-acquired slot for guaranteed cleanup even if tenant injection fails
    preacquired_tenant_id: UUID | None = None

    # Track sessions for cleanup (addresses session lifecycle leak on recovery)
    # When we recover from invalid transaction, we create new sessions that must be
    # closed in the finally block to prevent connection pool exhaustion
    created_sessions: list[AsyncSession] = []
    # Use mutable holder so page loop and heartbeat can access current session
    # This allows session recovery to update the reference mid-processing
    session_holder: dict = {"session": None, "uploader": None}

    # CRITICAL: Check for pre-acquired slot BEFORE tenant injection
    # Why: If feeder acquired a slot but tenant injection fails, we must still release
    # This read is safe even without tenant context
    try:
        _early_redis = container.redis_client()
        preacquired_key = f"job:{job_id}:slot_preacquired"
        preacquired_value = await _early_redis.get(preacquired_key)
        if preacquired_value:
            # Store tenant_id for guaranteed cleanup in finally block
            preacquired_tenant_id = UUID(preacquired_value.decode())
            # NOTE: Do NOT delete flag here - keep it for entire crawl lifecycle
            # Why: Heartbeat refreshes flag TTL, watchdog uses flag for crash recovery
            # Flag will be deleted in finally block after slot release
            logger.debug(
                "Pre-acquired slot detected, will ensure release",
                extra={"job_id": str(job_id), "tenant_id": str(preacquired_tenant_id)},
            )
    except Exception as exc:
        logger.warning(
            "Failed to check pre-acquired slot early",
            extra={"job_id": str(job_id), "error": str(exc)},
        )

    try:
        tenant = container.tenant()
    except Exception:  # pragma: no cover - defensive guard when tenant not injected
        tenant = None

    if tenant:
        limiter = container.tenant_concurrency_limiter()
        try:
            redis_client = container.redis_client()
        except Exception:  # pragma: no cover - container guard
            redis_client = None

        # FALLBACK: If early check failed (transient Redis error), retry now
        # Why: Early check runs before tenant injection. If it failed, the flag
        # is still in Redis and we'd double-acquire without this retry.
        if preacquired_tenant_id is None and redis_client:
            try:
                preacquired_key = f"job:{job_id}:slot_preacquired"
                preacquired_value = await redis_client.get(preacquired_key)
                if preacquired_value:
                    preacquired_tenant_id = UUID(preacquired_value.decode())
                    # NOTE: Do NOT delete flag here - keep it for entire crawl lifecycle
                    # Flag will be deleted in finally block after slot release
                    logger.debug(
                        "Pre-acquired slot detected on retry (early check failed)",
                        extra={
                            "job_id": str(job_id),
                            "tenant_id": str(preacquired_tenant_id),
                        },
                    )
            except Exception:
                pass  # Best effort - will acquire normally if this fails too

        # Check if we already detected a pre-acquired slot in early check
        # The early check happens BEFORE tenant injection to ensure cleanup even if injection fails
        if preacquired_tenant_id is not None:
            if preacquired_tenant_id == tenant.id:
                # Normal case: feeder pre-acquired slot for this tenant
                acquired = True
                logger.debug(
                    "Slot pre-acquired by feeder, skipping limiter.acquire()",
                    extra={"job_id": str(job_id), "tenant_id": str(tenant.id)},
                )
                # Refresh semaphore TTL - we now own this slot
                # Why: Normal acquire() refreshes TTL via Lua script. When we skip acquire,
                # we must manually refresh to prevent semaphore expiry during long queue times.
                if redis_client:
                    try:
                        semaphore_ttl = get_crawler_setting(
                            "tenant_worker_semaphore_ttl_seconds",
                            tenant.crawler_settings
                            if hasattr(tenant, "crawler_settings")
                            else None,
                            default=settings.tenant_worker_semaphore_ttl_seconds,
                        )
                        concurrency_key = f"tenant:{tenant.id}:active_jobs"
                        await redis_client.expire(concurrency_key, semaphore_ttl)
                    except Exception:
                        pass  # Best effort - slot is still valid
            else:
                # EDGE CASE: Feeder and worker disagree on tenant_id
                # This should never happen in normal operation but we handle it defensively
                logger.error(
                    "Tenant ID mismatch between feeder and worker",
                    extra={
                        "job_id": str(job_id),
                        "feeder_tenant_id": str(preacquired_tenant_id),
                        "worker_tenant_id": str(tenant.id),
                        "action": "releasing_feeder_slot_and_acquiring_new",
                    },
                )
                # Release the mismatched slot to prevent leak
                if redis_client:
                    try:
                        # Use per-tenant TTL if available
                        semaphore_ttl = get_crawler_setting(
                            "tenant_worker_semaphore_ttl_seconds",
                            tenant.crawler_settings
                            if hasattr(tenant, "crawler_settings")
                            else None,
                            default=settings.tenant_worker_semaphore_ttl_seconds,
                        )
                        release_key = f"tenant:{preacquired_tenant_id}:active_jobs"
                        await redis_client.eval(
                            LuaScripts.RELEASE_SLOT,
                            1,
                            release_key,
                            str(semaphore_ttl),
                        )
                    except Exception:
                        pass  # Best effort
                # Clear preacquired_tenant_id so finally block doesn't double-release
                preacquired_tenant_id = None
                # Acquire slot for the correct tenant
                acquired = await limiter.acquire(tenant.id)
        else:
            # No pre-acquired slot, acquire normally
            acquired = await limiter.acquire(tenant.id)

        if not acquired:
            # Enforce max age limit with exponential backoff to prevent infinite retry loops.
            # Concurrency limit (busy signal) is NOT counted as a failure - only age is checked.
            # This prevents jobs from being abandoned just because they're waiting for a slot.

            # Get per-tenant max age setting (falls back to env default)
            tenant_crawler_settings = tenant.crawler_settings if tenant else None
            max_age_seconds = get_crawler_setting(
                "crawl_job_max_age_seconds",
                tenant_crawler_settings,
                default=settings.crawl_job_max_age_seconds,
            )

            # Update stats with is_actual_failure=False (this is a busy signal, not a real failure)
            failure_count, job_age = await update_job_retry_stats(
                job_id=job_id,
                redis_client=redis_client,
                is_actual_failure=False,  # CRITICAL: Don't count busy waits as failures
                max_age_seconds=max_age_seconds,
            )

            # Check if max job age exceeded (ONLY age check for busy signals)
            if job_age > max_age_seconds:
                # Update crawl_run status before abandoning to prevent orphaned DB records
                # NOTE: Uses session_scope() for short-lived DB operation (~50ms)
                try:
                    async with Container.session_scope():
                        crawl_run_repo = container.crawl_run_repo()
                        crawl_run = await crawl_run_repo.one(params.run_id)
                        from intric.main.models import Status

                        crawl_run.status = Status.FAILED
                        await crawl_run_repo.update(crawl_run)
                except Exception as update_exc:
                    logger.warning(
                        "Failed to update crawl_run status on terminal",
                        extra={"run_id": str(params.run_id), "error": str(update_exc)},
                    )

                # Cleanup Redis counters to prevent memory leak
                if redis_client:
                    try:
                        await redis_client.delete(
                            f"job:{job_id}:start_time", f"job:{job_id}:retry_count"
                        )
                    except Exception:
                        pass  # Best effort cleanup

                logger.error(
                    "Crawl job permanently failed: Maximum retry age exceeded (busy wait)",
                    extra={
                        "job_id": str(job_id),
                        "tenant_id": str(tenant.id),
                        "tenant_slug": tenant.slug,
                        "website_id": str(params.website_id),
                        "url": params.url,
                        "job_age_seconds": job_age,
                        "max_age_seconds": max_age_seconds,
                        "failure_count": failure_count,
                        "failure_reason": "max_age_exceeded_busy",
                        "metric_name": "crawl.job.abandoned.max_age",
                        "metric_value": 1,
                    },
                )
                raise RuntimeError(
                    f"Crawl job {job_id} abandoned after {job_age:.0f}s "
                    f"(max: {max_age_seconds}s) - still waiting for concurrency slot"
                )

            # Calculate shorter backoff for busy signals (we're just waiting for a slot, not a failure)
            # Use random jitter to prevent thundering herd when slots open up
            retry_delay = random.uniform(10, 30)  # Short random delay for busy waits

            # Get per-tenant concurrency limit for logging
            concurrency_limit = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant_crawler_settings,
                default=settings.tenant_worker_concurrency_limit,
            )

            logger.warning(
                "Tenant concurrency limit reached, requeueing crawl (busy wait)",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(tenant.id),
                    "tenant_slug": tenant.slug,
                    "website_id": str(params.website_id),
                    "url": params.url,
                    "max_concurrent": concurrency_limit,
                    "failure_count": failure_count,
                    "retry_delay_seconds": retry_delay,
                    "job_age_seconds": job_age,
                    "signal_type": "busy",
                    "metric_name": "tenant.limiter.requeued",
                    "metric_value": 1,
                },
            )
            raise Retry(defer=retry_delay)

    primary_job_id: UUID | None = None
    if tenant is not None:
        try:
            async with Container.session_scope() as session:
                primary_job_id = await _get_primary_active_job_id(
                    session,
                    website_id=params.website_id,
                )

                if primary_job_id and primary_job_id != job_id:
                    from intric.database.tables.job_table import Jobs
                    from intric.main.models import Status

                    skip_message = (
                        f"Skipped duplicate crawl; active job {primary_job_id}"
                    )
                    stmt = (
                        sa.update(Jobs)
                        .where(Jobs.id == job_id)
                        .where(
                            Jobs.status.in_(
                                [Status.QUEUED.value, Status.IN_PROGRESS.value]
                            )
                        )
                        .values(
                            status=Status.FAILED.value,
                            finished_at=datetime.now(timezone.utc),
                            result_location=skip_message,
                        )
                    )
                    result = await session.execute(stmt)
                    if result.rowcount == 0:
                        logger.debug(
                            "Duplicate crawl skip ignored; job status already changed",
                            extra={
                                "job_id": str(job_id),
                                "website_id": str(params.website_id),
                            },
                        )

            if primary_job_id and primary_job_id != job_id:
                logger.warning(
                    "Skipping duplicate crawl job; another active job exists",
                    extra={
                        "job_id": str(job_id),
                        "primary_job_id": str(primary_job_id),
                        "website_id": str(params.website_id),
                        "url": params.url,
                        "metric_name": "crawl.job.duplicate_skipped",
                        "metric_value": 1,
                    },
                )
                task_manager._job_already_handled = True
                return {
                    "status": "duplicate_skipped",
                    "job_id": str(job_id),
                    "primary_job_id": str(primary_job_id),
                }
        except Exception as exc:
            logger.warning(
                "Failed to evaluate duplicate crawl guard; proceeding with crawl",
                extra={
                    "job_id": str(job_id),
                    "website_id": str(params.website_id),
                    "error": str(exc),
                },
            )

    try:
        # CRITICAL: Atomic status check to prevent worker resurrection
        # Why: Safe Watchdog may have marked this job FAILED while it was in ARQ queue.
        # Without this check, we'd blindly set IN_PROGRESS, "resurrecting" a dead job.
        # This uses Compare-and-Swap: only transitions QUEUED → IN_PROGRESS
        # NOTE: Uses session_scope() for short-lived DB operation (~50ms)
        async with Container.session_scope():
            job_repo_for_atomic_check = container.job_repo()
            job_started = await job_repo_for_atomic_check.mark_job_started(job_id)

        if not job_started:
            # Job status changed externally (likely FAILED by watchdog)
            # We must NOT process this job - abort immediately
            logger.warning(
                "Worker resurrection prevented: job status changed externally",
                extra={
                    "job_id": str(job_id),
                    "website_id": str(params.website_id),
                    "url": params.url,
                    "tenant_id": str(tenant.id) if tenant else None,
                    "acquired_new_slot": acquired and preacquired_tenant_id is None,
                    "metric_name": "crawl.worker.resurrection_prevented",
                    "metric_value": 1,
                },
            )

            # CRITICAL: Prevent finally block from releasing slot!
            # The Watchdog ALREADY released the slot when it marked job FAILED.
            # If we release again, we'd "steal" a slot from another running job.
            # Clear both flags to ensure neither finally path triggers:
            # - Primary path: if acquired → release (blocked by acquired=False)
            # - Fallback path: elif preacquired_tenant_id and not acquired → release (blocked by None)
            acquired = False
            preacquired_tenant_id = None

            return {"status": "resurrection_prevented", "job_id": str(job_id)}

        # Job successfully transitioned to IN_PROGRESS, pass flag to skip redundant update
        async with task_manager.set_status_on_exception(status_already_set=True):
            # Initialize timing tracking for performance analysis
            timings = {
                "fetch_existing_titles": 0.0,
                "crawl_and_parse": 0.0,
                "process_pages": 0.0,
                "process_files": 0.0,
                "cleanup_deleted": 0.0,
                "update_size": 0.0,
            }

            # Get resources (these don't need a session)
            crawler = container.crawler()
            uploader = container.text_processor()

            # Initialize session holder for recovery support
            # NOTE: Starts with None - sessions are created on-demand by execute_with_recovery
            # This is the "sessionless container" pattern for long-running tasks
            # Each DB operation creates its own short-lived session (~50-300ms)
            session_holder["session"] = None
            session_holder["uploader"] = uploader

            # BOOTSTRAP PHASE: Short-lived session for initial queries (~50-100ms)
            # Extract all needed data as primitives BEFORE the long crawl so the
            # session returns to pool immediately. This prevents holding a connection
            # for 5-30 minutes during the actual crawl operation.
            from intric.database.database import sessionmanager
            from intric.database.tables.websites_table import Websites as WebsitesTable
            from intric.database.tables.info_blobs_table import InfoBlobs

            # These will be populated by bootstrap
            crawl_context: CrawlContext
            existing_titles: list[str] = []
            existing_file_hashes: dict[str, bytes] = {}
            website_url: str = ""  # For logging after session closes

            start = time.time()
            # Bootstrap phase: Short-lived session for extracting ORM → DTO
            # All data is converted to EmbeddingModelSpec/CrawlContext DTOs before session closes,
            # preventing DetachedInstanceError when embedding APIs are called later.
            bootstrap_session = sessionmanager.create_session()
            try:
                await bootstrap_session.begin()
                # Get website with eager loading of embedding_model
                from intric.database.tables.websites_table import Websites
                from sqlalchemy.orm import selectinload

                website_stmt = (
                    sa.select(Websites)
                    .where(Websites.id == params.website_id)
                    .options(selectinload(Websites.embedding_model))
                )
                result = await bootstrap_session.execute(website_stmt)
                website = result.scalar_one_or_none()

                if website is None:
                    raise Exception(f"Website {params.website_id} not found")

                website_url = website.url  # Save for logging after session closes

                # CRITICAL: Verify tenant isolation
                current_tenant = container.tenant()
                if website.tenant_id != current_tenant.id:
                    logger.error(
                        "Tenant isolation violation detected",
                        extra={
                            "website_id": str(params.website_id),
                            "website_tenant_id": str(website.tenant_id),
                            "container_tenant_id": str(current_tenant.id),
                        },
                    )
                    raise Exception(
                        f"Tenant isolation violation: website {params.website_id} "
                        f"belongs to tenant {website.tenant_id}, not {current_tenant.id}"
                    )

                # Extract HTTP auth credentials if present
                # NOTE: Using ORM columns directly (http_auth_username, encrypted_auth_password)
                # because we're working with the raw Websites table, not the domain model
                http_user = None
                http_pass = None
                has_auth_in_db = bool(
                    website.http_auth_username and website.encrypted_auth_password
                )

                if has_auth_in_db:
                    # Decrypt the password using HttpAuthEncryptionService (NOT encryption_service)
                    # HttpAuthEncryptionService uses its own Fernet encryption format
                    # while encryption_service expects 'enc:' prefix format
                    try:
                        http_auth_encryption = container.http_auth_encryption_service()
                        http_user = website.http_auth_username
                        http_pass = http_auth_encryption.decrypt_password(
                            website.encrypted_auth_password
                        )
                        logger.info(
                            "HTTP auth configured for website",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(website.tenant_id),
                            },
                        )
                    except Exception as decrypt_err:
                        logger.error(
                            "Cannot crawl website: HTTP auth decryption failed. "
                            "Check encryption_key setting is correct.",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(website.tenant_id),
                                "error": str(decrypt_err),
                            },
                        )
                        raise Exception(
                            f"HTTP auth decryption failed for website {params.website_id}. "
                            "Check encryption_key configuration."
                        )

                # Extract embedding model into EmbeddingModelSpec DTO
                # This extracts ALL primitives from ORM while session is active,
                # preventing DetachedInstanceError when session closes
                orm_embedding_model = website.embedding_model
                embedding_model_spec: EmbeddingModelSpec | None = None
                if orm_embedding_model:
                    # Convert family string to ModelFamily enum
                    # DB stores string (e.g., "openai"), but adapters expect enum
                    family_enum: ModelFamily | None = None
                    if orm_embedding_model.family:
                        try:
                            family_enum = ModelFamily(orm_embedding_model.family)
                        except ValueError:
                            logger.warning(
                                "Unknown ModelFamily value from DB, using None",
                                extra={
                                    "family": orm_embedding_model.family,
                                    "model_name": orm_embedding_model.name,
                                },
                            )

                    embedding_model_spec = EmbeddingModelSpec(
                        id=orm_embedding_model.id,
                        name=orm_embedding_model.name,
                        litellm_model_name=orm_embedding_model.litellm_model_name,
                        family=family_enum,
                        max_input=orm_embedding_model.max_input,
                        max_batch_size=orm_embedding_model.max_batch_size,
                        dimensions=orm_embedding_model.dimensions,
                        open_source=orm_embedding_model.open_source,
                    )

                # Build CrawlContext DTO from ORM objects
                # Extract ALL fields as primitives to avoid DetachedInstanceError
                crawl_context = CrawlContext(
                    website_id=website.id,
                    tenant_id=website.tenant_id,
                    tenant_slug=tenant.slug if tenant else None,
                    user_id=container.user().id,
                    # Embedding model - use EmbeddingModelSpec DTO (already extracted)
                    embedding_model_id=embedding_model_spec.id
                    if embedding_model_spec
                    else None,
                    embedding_model_name=embedding_model_spec.name
                    if embedding_model_spec
                    else None,
                    embedding_model_open_source=embedding_model_spec.open_source
                    if embedding_model_spec
                    else False,
                    embedding_model_family=(
                        embedding_model_spec.family
                        if embedding_model_spec and embedding_model_spec.family
                        else None
                    ),
                    embedding_model_dimensions=(
                        embedding_model_spec.dimensions
                        if embedding_model_spec
                        else None
                    ),
                    # HTTP Auth - primitives only
                    http_auth_user=http_user,
                    http_auth_pass=http_pass,
                    # Batch settings from tenant config with defaults
                    batch_size=get_crawler_setting(
                        "crawl_page_batch_size",
                        tenant.crawler_settings if tenant else None,
                        default=settings.crawl_page_batch_size,
                    ),
                )

                # Fetch existing titles for stale detection and file hashes for skip optimization
                stmt = sa.select(InfoBlobs.title, InfoBlobs.content_hash).where(
                    InfoBlobs.website_id == params.website_id
                )
                blob_result = await bootstrap_session.execute(stmt)

                # Build lookups for O(1) operations
                for title, hash_bytes in blob_result:
                    existing_titles.append(title)
                    # Only store hashes for files (not URLs)
                    if hash_bytes is not None and not title.startswith("http"):
                        existing_file_hashes[title] = hash_bytes

            finally:
                # Always close the bootstrap session to return connection to pool
                await bootstrap_session.close()

            # Session returned to pool HERE - bootstrap complete (~50-100ms)
            timings["fetch_existing_titles"] = time.time() - start

            logger.info(
                "Bootstrap phase complete - session returned to pool",
                extra={
                    "website_id": str(params.website_id),
                    "tenant_id": str(crawl_context.tenant_id),
                    "batch_size": crawl_context.batch_size,
                    "embedding_model": crawl_context.embedding_model_name,
                    "existing_titles_count": len(existing_titles),
                    "bootstrap_duration_ms": int(
                        timings["fetch_existing_titles"] * 1000
                    ),
                },
            )

            # Do task
            logger.info(f"Running crawl with params: {params}")

            num_pages = 0
            num_files = 0
            num_failed_pages = 0
            num_failed_files = 0
            num_deleted_blobs = 0
            num_skipped_files = 0  # Files with unchanged content (hash match)

            # Use set for O(1) membership tests
            crawled_titles = set()
            failed_titles: set[str] = set()  # Failed URLs excluded from stale deletion

            # Get per-tenant settings for heartbeat BEFORE starting crawl
            # This ensures heartbeat runs during the entire crawl phase
            current_tenant = container.tenant()
            heartbeat_interval_seconds = get_crawler_setting(
                "crawl_heartbeat_interval_seconds",
                current_tenant.crawler_settings if current_tenant else None,
                default=settings.crawl_heartbeat_interval_seconds,
            )
            semaphore_ttl_seconds = get_crawler_setting(
                "tenant_worker_semaphore_ttl_seconds",
                tenant.crawler_settings
                if hasattr(tenant, "crawler_settings")
                else None,
                default=settings.tenant_worker_semaphore_ttl_seconds,
            )

            # Create heartbeat monitor BEFORE crawl starts
            # This allows heartbeat to run during the Scrapy crawl phase (which can take 30+ minutes)
            heartbeat_monitor = HeartbeatMonitor(
                job_id=job_id,
                redis_client=redis_client,
                tenant=tenant,
                interval_seconds=heartbeat_interval_seconds,
                max_failures=settings.crawl_heartbeat_max_failures,
                semaphore_ttl_seconds=semaphore_ttl_seconds,
            )

            # Use Scrapy crawler to process website content
            # Measure crawl and parse phase
            start = time.time()
            async with crawler.crawl(
                url=params.url,
                download_files=params.download_files,
                crawl_type=params.crawl_type,
                http_user=crawl_context.http_auth_user,  # From bootstrap DTO
                http_pass=crawl_context.http_auth_pass,  # From bootstrap DTO
                # Pass tenant settings for tenant-aware Scrapy configuration
                tenant_crawler_settings=tenant.crawler_settings if tenant else None,
                # Pass heartbeat callback for liveness during Scrapy crawl phase
                heartbeat_callback=heartbeat_monitor.tick,
                heartbeat_interval=float(heartbeat_interval_seconds),
            ) as crawl:
                timings["crawl_and_parse"] = time.time() - start

                # Track partial completion status for logging
                crawl_is_partial = crawl.is_partial
                crawl_termination_reason = crawl.termination_reason

                if crawl_is_partial:
                    logger.warning(
                        f"Crawl timed out but has partial results - salvaging {crawl.pages_count} pages",
                        extra={
                            "job_id": str(job_id),
                            "website_id": str(params.website_id),
                            "url": params.url,
                            "pages_collected": crawl.pages_count,
                            "termination_reason": crawl_termination_reason,
                        },
                    )

                # Measure page processing time
                process_start = time.time()

                # Session-per-batch page processing (NO main session held)
                # Bootstrap already returned session to pool. All DB operations
                # use session_scope() or persist_batch() which manage their own sessions.
                # Get services needed for persist_batch
                # NOTE: embedding_model was extracted during bootstrap phase
                create_embeddings_service = container.create_embeddings_service()

                # Page buffer for batching (primitives only, NO ORM objects!)
                page_buffer: list[dict] = []

                for page in crawl.pages:
                    num_pages += 1

                    # Heartbeat: touches DB, refreshes Redis TTL, checks preemption
                    try:
                        await heartbeat_monitor.tick()
                    except HeartbeatFailedError as e:
                        return {
                            "status": "heartbeat_failed",
                            "pages_crawled": num_pages,
                            "consecutive_failures": e.consecutive_failures,
                        }
                    except JobPreemptedError:
                        logger.warning(
                            "Detected job preemption during heartbeat",
                            extra={
                                "job_id": str(job_id),
                                "website_id": str(params.website_id),
                                "pages_processed": num_pages,
                            },
                        )
                        return {
                            "status": "preempted_during_crawl",
                            "pages_crawled": num_pages,
                        }

                    # Buffer page as dict (primitives only!)
                    page_buffer.append(
                        {
                            "url": page.url,
                            "content": page.content,
                        }
                    )

                    # Flush when buffer is full
                    if len(page_buffer) >= crawl_context.batch_size:
                        (
                            success_count,
                            failed_count,
                            successful_urls,
                            batch_failed_urls,
                        ) = await persist_batch(
                            page_buffer=page_buffer,
                            ctx=crawl_context,
                            embedding_model=embedding_model_spec,
                            create_embeddings_service=create_embeddings_service,
                        )
                        crawled_titles.update(successful_urls)
                        failed_titles.update(batch_failed_urls)
                        num_failed_pages += failed_count
                        page_buffer.clear()

                        logger.debug(
                            f"Flushed batch of {crawl_context.batch_size} pages",
                            extra={
                                "job_id": str(job_id),
                                "success": success_count,
                                "failed": failed_count,
                                "total_pages": num_pages,
                            },
                        )

                # Final flush for remaining pages
                if page_buffer:
                    (
                        success_count,
                        failed_count,
                        successful_urls,
                        batch_failed_urls,
                    ) = await persist_batch(
                        page_buffer=page_buffer,
                        ctx=crawl_context,
                        embedding_model=embedding_model_spec,
                        create_embeddings_service=create_embeddings_service,
                    )
                    crawled_titles.update(successful_urls)
                    failed_titles.update(batch_failed_urls)
                    num_failed_pages += failed_count

                    logger.debug(
                        f"Final flush of {len(page_buffer)} pages",
                        extra={
                            "job_id": str(job_id),
                            "success": success_count,
                            "failed": failed_count,
                            "total_pages": num_pages,
                        },
                    )

                timings["process_pages"] = time.time() - process_start

                # Measure file processing time
                file_start = time.time()
                # Process downloaded files with content hash checking
                # Uses session-per-file pattern: each file gets its own short-lived session
                for file in crawl.files:
                    num_files += 1
                    try:
                        filename = file.stem

                        # ✅ PERFORMANCE OPTIMIZATION: Hash checking for files
                        # Hash raw bytes directly (no HTML normalization for files)
                        file_bytes = file.read_bytes()
                        new_file_hash = hashlib.sha256(file_bytes).digest()

                        existing_file_hash = existing_file_hashes.get(filename)

                        if (
                            existing_file_hash is not None
                            and new_file_hash == existing_file_hash
                        ):
                            # File unchanged - skip processing
                            num_skipped_files += 1
                            crawled_titles.add(filename)
                            logger.debug(
                                f"Skipping unchanged file: {filename}",
                                extra={
                                    "website_id": str(params.website_id),
                                    "file_name": filename,
                                },
                            )
                            continue

                        # File changed or new - process with session-per-file pattern
                        # Each file gets its own short-lived session (~50-300ms)
                        async def _process_single_file(sess):
                            # Get fresh text processor with this session
                            container.session.override(providers.Object(sess))
                            file_uploader = container.text_processor()
                            await file_uploader.process_file(
                                filepath=file,
                                filename=filename,
                                website_id=params.website_id,
                                embedding_model=embedding_model_spec,
                                content_hash=new_file_hash,
                            )

                        await execute_with_recovery(
                            container=container,
                            session_holder=session_holder,
                            created_sessions=created_sessions,
                            operation_name=f"process_file_{filename}",
                            operation=_process_single_file,
                        )
                        crawled_titles.add(filename)

                    except Exception:
                        logger.exception(
                            "Exception while uploading file",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(crawl_context.tenant_id),
                                "crawled_filename": filename,
                                "embedding_model": crawl_context.embedding_model_name,
                            },
                        )
                        num_failed_files += 1
                timings["process_files"] = time.time() - file_start

            # Cleanup phase: delete stale blobs (batch for performance)
            cleanup_start = time.time()
            # Exclude failed_titles - their original data was preserved by transaction rollback
            stale_titles = [
                title
                for title in existing_titles
                if title not in crawled_titles and title not in failed_titles
            ]

            # Batch delete using session-per-operation pattern
            if stale_titles:

                async def _do_stale_blob_cleanup(sess):
                    # Get fresh repo with this session
                    container.session.override(providers.Object(sess))
                    cleanup_repo = container.info_blob_repo()
                    return await cleanup_repo.batch_delete_by_titles_and_website(
                        titles=stale_titles, website_id=params.website_id
                    )

                num_deleted_blobs = await execute_with_recovery(
                    container=container,
                    session_holder=session_holder,
                    created_sessions=created_sessions,
                    operation_name="stale_blob_cleanup",
                    operation=_do_stale_blob_cleanup,
                )
                if num_deleted_blobs > 0:
                    logger.info(
                        f"Batch deleted {num_deleted_blobs} stale blobs",
                        extra={
                            "website_id": str(params.website_id),
                            "num_stale": len(stale_titles),
                            "num_deleted": num_deleted_blobs,
                        },
                    )
            else:
                num_deleted_blobs = 0
            timings["cleanup_deleted"] = time.time() - cleanup_start

            # Measure website size update with recovery wrapper
            update_start = time.time()

            async def _do_update_size(sess):
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # NOTE: Use crawl_context primitives, NOT detached ORM website object
                from intric.database.tables.info_blobs_table import (
                    InfoBlobs as InfoBlobsTable,
                )

                update_size_stmt = (
                    sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
                    .where(InfoBlobsTable.website_id == crawl_context.website_id)
                    .scalar_subquery()
                )
                stmt = (
                    sa.update(WebsitesTable)
                    .where(WebsitesTable.id == crawl_context.website_id)
                    .values(size=update_size_stmt)
                )
                await sess.execute(stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="website_size_update",
                operation=_do_update_size,
            )
            timings["update_size"] = time.time() - update_start

            # Update last_crawled_at timestamp with recovery wrapper
            # Why: Track crawl completion time independently from record updates
            # Use database server time for timezone correctness
            # NOTE: WebsitesTable already imported above for bootstrap phase

            last_crawled_stmt = (
                sa.update(WebsitesTable)
                .where(WebsitesTable.id == params.website_id)
                .where(
                    WebsitesTable.tenant_id == crawl_context.tenant_id
                )  # Tenant isolation
                .values(last_crawled_at=sa.func.now())
            )

            async def _do_timestamp_update(sess):
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # No need for transaction check - execute_with_recovery handles it
                await sess.execute(last_crawled_stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="last_crawled_at_update",
                operation=_do_timestamp_update,
            )

            # Calculate file skip rate for performance analysis
            file_skip_rate = (
                (num_skipped_files / num_files * 100) if num_files > 0 else 0
            )

            # Structured crawl summary for easy log scanning
            status_label = (
                f"CRAWL PARTIAL ({crawl_termination_reason})"
                if crawl_is_partial
                else "CRAWL FINISHED"
            )
            summary = [
                "=" * 60,
                f"{status_label}: {params.url}",
                "-" * 60,
                f"Pages:   {num_pages} crawled, {num_failed_pages} failed",
                f"Files:   {num_files} downloaded, {num_failed_files} failed, {num_skipped_files} skipped ({file_skip_rate:.1f}%)",
                f"Cleanup: {num_deleted_blobs} stale entries removed",
            ]
            if crawl_is_partial:
                summary.append(
                    f"⚠️  Partial completion due to: {crawl_termination_reason}"
                )
            summary.append("=" * 60)
            logger.info("\n".join(summary))

            # Performance breakdown log for analysis
            total_time = sum(timings.values())
            logger.info(
                f"Performance breakdown: "
                f"fetch_existing={timings['fetch_existing_titles']:.2f}s, "
                f"crawl_parse={timings['crawl_and_parse']:.2f}s, "
                f"process_pages={timings['process_pages']:.2f}s, "
                f"process_files={timings['process_files']:.2f}s, "
                f"cleanup={timings['cleanup_deleted']:.2f}s, "
                f"update_size={timings['update_size']:.2f}s, "
                f"total_measured={total_time:.2f}s",
                extra={
                    "timings": timings,
                    "pages_crawled": num_pages,
                    "pages_failed": num_failed_pages,
                    "files_crawled": num_files,
                    "files_failed": num_failed_files,
                    "files_skipped": num_skipped_files,
                    "file_skip_rate_percent": file_skip_rate,
                    "blobs_deleted": num_deleted_blobs,
                },
            )

            # Preemption check: Verify job wasn't marked FAILED while we were crawling.
            # If preempted, don't write results - a new crawl is already running.
            from intric.main.models import Status as JobStatus
            from intric.database.tables.job_table import Jobs

            async def _do_suicide_check(sess):
                # Session provided by execute_with_recovery (session-per-operation pattern)
                result = await sess.execute(
                    sa.select(Jobs.status).where(Jobs.id == job_id)
                )
                return result.scalar_one_or_none()

            job_status_value = await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="suicide_check",
                operation=_do_suicide_check,
            )

            if job_status_value == JobStatus.FAILED.value:
                logger.warning(
                    "Crawl job was preempted during execution - aborting without writing results",
                    extra={
                        "job_id": str(job_id),
                        "website_id": str(params.website_id),
                        "pages_crawled": num_pages,
                        "files_crawled": num_files,
                    },
                )
                # Don't write results - exit gracefully
                # Note: Downloaded pages/files were already processed, but we won't update
                # the crawl_run or website stats since a new crawl should handle that
                return {"status": "preempted", "pages_crawled": num_pages}

            # Update crawl run with recovery wrapper
            from intric.database.tables.websites_table import CrawlRuns

            async def _do_crawl_run_update(sess):
                # Session provided by execute_with_recovery (session-per-operation pattern)
                stmt = (
                    sa.update(CrawlRuns)
                    .where(CrawlRuns.id == params.run_id)
                    .values(
                        pages_crawled=num_pages,
                        files_downloaded=num_files,
                        pages_failed=num_failed_pages,
                        files_failed=num_failed_files,
                    )
                )
                await sess.execute(stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="crawl_run_update",
                operation=_do_crawl_run_update,
            )

            # Circuit breaker: Update failure tracking and exponential backoff

            # Determine if crawl was successful
            # Success = at least one item (page or file) AND not everything failed
            total_items = num_pages + num_files
            total_failed = num_failed_pages + num_failed_files
            crawl_successful = total_items > 0 and total_failed < total_items

            async def _do_circuit_breaker_update(sess):
                """Update circuit breaker state with appropriate backoff/reset."""
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # NOTE: Use crawl_context primitives, NOT detached ORM website object
                if crawl_successful:
                    # Success: Reset circuit breaker
                    logger.info(
                        f"Crawl successful, resetting circuit breaker for website {params.website_id}"
                    )
                    reset_stmt = (
                        sa.update(WebsitesTable)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                        .values(consecutive_failures=0, next_retry_at=None)
                    )
                    await sess.execute(reset_stmt)
                else:
                    # Failure: Increment counter and apply exponential backoff
                    # Get current failure count (with tenant filter for security)
                    current_failures_stmt = (
                        sa.select(WebsitesTable.consecutive_failures)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                    )
                    current_failures = await sess.scalar(current_failures_stmt) or 0
                    new_failures = current_failures + 1

                    # Auto-disable threshold: Stop trying after too many failures
                    MAX_FAILURES_BEFORE_DISABLE = 10

                    if new_failures >= MAX_FAILURES_BEFORE_DISABLE:
                        # Auto-disable: Set update_interval to NEVER
                        from intric.websites.domain.website import UpdateInterval

                        logger.error(
                            f"Website {params.website_id} auto-disabled after {new_failures} consecutive failures. "
                            f"User action required to re-enable.",
                            extra={
                                "website_id": str(params.website_id),
                                "url": website_url,  # Use primitive captured during bootstrap
                                "consecutive_failures": new_failures,
                            },
                        )

                        disable_stmt = (
                            sa.update(WebsitesTable)
                            .where(WebsitesTable.id == params.website_id)
                            .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                            .values(
                                consecutive_failures=new_failures,
                                update_interval=UpdateInterval.NEVER,  # Auto-disable
                                next_retry_at=None,  # Clear retry time
                            )
                        )
                        await sess.execute(disable_stmt)
                    else:
                        # Normal exponential backoff: 1h, 2h, 4h, 8h, 16h, 24h max
                        backoff_hours = min(2 ** (new_failures - 1), 24)
                        next_retry = datetime.now(timezone.utc) + timedelta(
                            hours=backoff_hours
                        )

                        logger.warning(
                            f"Crawl failed for website {params.website_id}. "
                            f"Failure {new_failures}/{MAX_FAILURES_BEFORE_DISABLE}, "
                            f"backoff {backoff_hours}h until {next_retry.isoformat()}",
                            extra={
                                "website_id": str(params.website_id),
                                "consecutive_failures": new_failures,
                                "backoff_hours": backoff_hours,
                                "next_retry_at": next_retry.isoformat(),
                            },
                        )

                        backoff_stmt = (
                            sa.update(WebsitesTable)
                            .where(WebsitesTable.id == params.website_id)
                            .where(WebsitesTable.tenant_id == crawl_context.tenant_id)
                            .values(
                                consecutive_failures=new_failures,
                                next_retry_at=next_retry,
                            )
                        )
                        await sess.execute(backoff_stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="circuit_breaker_update",
                operation=_do_circuit_breaker_update,
            )

            # Audit logging for website crawl
            from intric.audit.domain.action_types import ActionType
            from intric.audit.domain.entity_types import EntityType

            audit_service = container.audit_service()

            # Determine actor (crawl is typically triggered by a user or system)
            # Use website owner or system actor
            actor_id = (
                website.user_id
                if hasattr(website, "user_id") and website.user_id
                else current_tenant.id
            )

            await audit_service.log_async(
                tenant_id=current_tenant.id,
                actor_id=actor_id,
                action=ActionType.WEBSITE_CRAWLED,
                entity_type=EntityType.WEBSITE,
                entity_id=params.website_id,
                description=f"Website crawled: {website.url} - {'Success' if crawl_successful else 'Failed'}",
                metadata={
                    "target": {
                        "website_id": str(params.website_id),
                        "url": website.url,
                        "name": getattr(website, "name", website.url),
                    },
                    "crawl_stats": {
                        "pages_crawled": num_pages,
                        "pages_failed": num_failed_pages,
                        "files_downloaded": num_files,
                        "files_failed": num_failed_files,
                        "files_skipped": num_skipped_files,
                        "blobs_deleted": num_deleted_blobs,
                        "successful": crawl_successful,
                    },
                },
            )

            task_manager.result_location = (
                f"/api/v1/websites/{params.website_id}/info-blobs/"
            )

            # Complete job with session-per-operation pattern
            async def _do_complete_job(sess):
                """Complete the job with session provided by execute_with_recovery."""
                from intric.database.tables.job_table import Jobs
                from intric.main.models import Status

                stmt = (
                    sa.update(Jobs)
                    .where(Jobs.id == job_id)
                    .values(
                        status=Status.COMPLETE.value,
                        finished_at=datetime.now(timezone.utc),
                        result_location=task_manager.result_location,
                    )
                )
                await sess.execute(stmt)
                # No explicit commit - execute_with_recovery handles it

                logger.debug(
                    "Job completed via session-per-operation pattern",
                    extra={"job_id": str(job_id)},
                )

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="complete_job",
                operation=_do_complete_job,
            )

            # Signal task_manager to skip its complete_job() call
            # Why: We've already completed the job with a fresh session above,
            # task_manager's job_service has stale session references
            task_manager._job_already_handled = True

        return task_manager.successful()
    finally:
        # Primary path: normal release when everything worked
        if limiter is not None and tenant is not None and acquired:
            await limiter.release(tenant.id)
            await reset_tenant_retry_delay(
                tenant_id=tenant.id, redis_client=redis_client
            )
            # Delete pre-acquired flag after slot release
            # Why: Flag must persist during crawl for heartbeat TTL refresh and watchdog crash recovery
            # Deleting here (not earlier) ensures flag exists for entire crawl lifecycle
            if redis_client and job_id:
                try:
                    await redis_client.delete(f"job:{job_id}:slot_preacquired")
                except Exception:
                    pass  # Best effort cleanup
        # Fallback path: release pre-acquired slot if tenant injection failed
        # This ensures we don't leak slots when the worker fails early
        elif preacquired_tenant_id is not None and not acquired:
            # Feeder acquired slot but we never set acquired=True
            # Must release directly via Redis to prevent leak
            logger.warning(
                "Releasing pre-acquired slot due to early failure",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(preacquired_tenant_id),
                    "reason": "tenant_injection_failed"
                    if tenant is None
                    else "acquired_not_set",
                },
            )
            try:
                # Try to get redis client if we don't have one
                _fallback_redis = redis_client
                if _fallback_redis is None:
                    try:
                        _fallback_redis = container.redis_client()
                    except Exception:
                        pass
                if _fallback_redis is not None:
                    release_key = f"tenant:{preacquired_tenant_id}:active_jobs"
                    # Redis eval executes Lua script atomically (not Python eval)
                    await _fallback_redis.eval(
                        LuaScripts.RELEASE_SLOT,
                        1,
                        release_key,
                        str(settings.tenant_worker_semaphore_ttl_seconds),
                    )
                    # Delete pre-acquired flag after fallback slot release
                    if job_id:
                        try:
                            await _fallback_redis.delete(
                                f"job:{job_id}:slot_preacquired"
                            )
                        except Exception:
                            pass  # Best effort cleanup
            except Exception as release_exc:
                logger.error(
                    "Failed to release pre-acquired slot in fallback",
                    extra={
                        "job_id": str(job_id),
                        "tenant_id": str(preacquired_tenant_id),
                        "error": str(release_exc),
                    },
                )
        # Third fallback: emergency flag read when both paths unavailable
        # Trigger: Both early Redis check AND tenant injection failed, leaving
        # tenant=None and preacquired_tenant_id=None, which skips both paths above.
        # This prevents slot leak until TTL in dual-failure scenarios.
        # Safety: Watchdog deletes flag when releasing, so if flag exists, slot needs release.
        elif (
            tenant is None and preacquired_tenant_id is None and not acquired and job_id
        ):
            # Get redis client with fallback to container
            _emergency_redis = redis_client
            if _emergency_redis is None:
                try:
                    _emergency_redis = container.redis_client()
                except Exception:
                    pass
            if _emergency_redis is not None:
                capacity_mgr = CapacityManager(_emergency_redis, settings)
                await capacity_mgr.emergency_release_slot(job_id)

        # Cleanup Redis retry counters to prevent memory leak
        if redis_client and job_id:
            try:
                await redis_client.delete(
                    f"job:{job_id}:start_time", f"job:{job_id}:retry_count"
                )
            except Exception:
                pass  # Best effort cleanup

        # Clean up recovery sessions to prevent connection pool exhaustion
        for recovery_session in created_sessions:
            try:
                await recovery_session.close()
            except Exception:
                pass  # Best effort cleanup

        # Guaranteed close with rollback for main session
        main_session = session_holder.get("session")
        if main_session is not None:
            try:
                # Only rollback if there's an active transaction
                if main_session.in_transaction():
                    await main_session.rollback()
            except Exception as rollback_exc:
                # Log at debug level - may be expected if session already closed
                logger.debug(
                    "Session rollback in finally block (may be expected)",
                    extra={"error": str(rollback_exc)},
                )
            try:
                await main_session.close()
            except Exception:
                pass  # Best effort - connection may already be closed
            finally:
                # Clear session_holder to prevent reuse of closed session
                session_holder["session"] = None
