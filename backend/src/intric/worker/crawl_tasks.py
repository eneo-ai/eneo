import random
import socket
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import redis.asyncio as aioredis
import sqlalchemy as sa
from arq import Retry
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from intric.crawler.crawler import CrawlDiagnostics, CrawlShutdownError
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.tenants.crawler_settings_helper import (
    TenantCrawlerSettings,
    get_crawler_setting,
)
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_cleanup_policy import cleanup_policy_for_outcome
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    CrawlOutcomeCrawlType,
    CrawlTerminationReason,
    FailureReason,
    classify_crawl_outcome,
)
from intric.websites.domain.crawl_run import CrawlType
from intric.worker.crawl import (
    CrawlAuditPayload,
    CrawlRunTerminalUpdate,
    CrawlSlotAcquireRequest,
    CrawlSlotReleaseRequest,
    ExistingBlobState,
    HeartbeatFailedPageProcessingAbort,
    HeartbeatMonitor,
    PageProcessingSuccess,
    PersistBatchResult,
    PreemptedPageProcessingAbort,
    SessionHolder,
    TerminalEvent,
    acquire_crawl_slot,
    bootstrap_crawl,
    cleanup_stale_blobs,
    commit_terminal,
    execute_with_recovery,
    persist_batch,
    process_files,
    process_pages,
    release_crawl_slot_after_task,
    update_job_retry_stats,
    update_website_timestamps_after_crawl,
)
from intric.worker.crawl.persistence import CrawlPageData
from intric.worker.crawl.post_terminal_effects import (
    PostTerminalEffectInput,
    PostTerminalRecoveryContext,
    apply_post_terminal_effects,
)
from intric.worker.crawl_context import EmbeddingModelSpec
from intric.worker.feeder.election import LeaderElection
from intric.worker.feeder.queues import CrawlPendingJobData, PendingQueue
from intric.worker.task_manager import TaskManager

logger = get_logger(__name__)

SCHEDULER_LOCK_KEY = "crawl_scheduler:leader"
SCHEDULER_LOCK_TTL_SECONDS = 1800
_TERMINAL_ZERO_OUTPUT_MESSAGES: dict[CrawlOutcomeCode, str] = {
    CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED: "Crawl produced no pages",
    CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES: "Sitemap crawl produced no pages",
    CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY: (
        "Crawl found files, but they exceeded the download size limit"
    ),
    CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES: (
        "Crawl timed out before collecting pages"
    ),
}


class CrawlMaxAgeExceededError(RuntimeError):
    pass


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
    from intric.jobs.job_models import Task
    from intric.main.models import Status

    active_statuses = [Status.QUEUED.value, Status.IN_PROGRESS.value]
    stmt = (
        sa.select(Jobs.id)
        .join(CrawlRunsTable, CrawlRunsTable.job_id == Jobs.id)
        .where(CrawlRunsTable.website_id == website_id)
        .where(Jobs.task == Task.CRAWL.value)
        .where(Jobs.status.in_(active_statuses))
        .order_by(Jobs.created_at.asc())
        .limit(1)
    )
    return await session.scalar(stmt)


def _build_http_cache_dir(*, root_dir: Path, tenant_id: UUID, website_id: UUID) -> Path:
    return root_dir / str(tenant_id) / str(website_id)


def _is_url_title(title: str) -> bool:
    return title.startswith(("http://", "https://"))


def _build_sitemap_lastmod_skip_urls(
    *,
    existing_blob_state_by_title: Mapping[str, ExistingBlobState],
    embedding_model_id: UUID | None,
) -> frozenset[str]:
    """Return URL blobs eligible for source-skip before page download.

    If the current embedding model is unavailable, existing URL blobs can still
    be retained because source-skip does not create or refresh embeddings.
    """
    return frozenset(
        title
        for title, blob_state in existing_blob_state_by_title.items()
        if _is_url_title(title)
        and (
            embedding_model_id is None
            or blob_state.embedding_model_id == embedding_model_id
        )
    )


def _should_enable_sitemap_lastmod_skip(
    *,
    crawl_type: CrawlType,
    website_last_source_verified_at: datetime | None,
    tenant_crawler_settings: TenantCrawlerSettings | None,
) -> bool:
    return (
        crawl_type == CrawlType.SITEMAP
        and website_last_source_verified_at is not None
        and get_crawler_setting(
            "crawl_sitemap_lastmod_skip_enabled",
            tenant_crawler_settings,
        )
    )


def _prune_http_cache_dir(cache_dir: Path, *, max_bytes: int) -> None:
    if max_bytes <= 0 or not cache_dir.exists():
        return

    files: list[tuple[float, int, Path]] = []
    total_bytes = 0
    for path in cache_dir.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        files.append((stat.st_mtime, stat.st_size, path))
        total_bytes += stat.st_size

    if total_bytes <= max_bytes:
        return

    for _, size, path in sorted(files):
        if total_bytes <= max_bytes:
            break
        try:
            path.unlink()
            total_bytes -= size
        except OSError:
            logger.warning(
                "Failed to prune crawler HTTP cache file",
                extra={"path": str(path), "cache_dir": str(cache_dir)},
            )


def _warn_if_retained_items_without_embedding_config(
    *,
    embedding_model: EmbeddingModelSpec | None,
    retained_pages: int,
    retained_files: int,
    website_id: UUID,
    tenant_id: UUID,
) -> None:
    retained_count = retained_pages + retained_files
    if retained_count == 0:
        return
    if (
        embedding_model is not None
        and embedding_model.provider_id is not None
        and embedding_model.provider_type is not None
    ):
        return

    logger.warning(
        "Embedding configuration is missing but unchanged crawl items were retained",
        extra={
            "reason": "embedding_misconfigured_but_no_changes",
            "website_id": str(website_id),
            "tenant_id": str(tenant_id),
            "retained_pages": retained_pages,
            "retained_files": retained_files,
            "retained_count": retained_count,
        },
    )


def _crawl_type_for_outcome(crawl_type: CrawlType) -> CrawlOutcomeCrawlType:
    if crawl_type == CrawlType.SITEMAP:
        return "sitemap"
    return "crawl"


def _terminal_zero_output_message(
    outcome_code: CrawlOutcomeCode | None,
    diagnostics: CrawlDiagnostics | None = None,
) -> str | None:
    if outcome_code is None:
        return None
    base_message = _TERMINAL_ZERO_OUTPUT_MESSAGES.get(outcome_code)
    if base_message is None:
        return None
    if diagnostics is None:
        return base_message

    diagnostic_detail = diagnostics.describe_empty_output()
    if not diagnostic_detail:
        return base_message
    return f"{base_message}: {diagnostic_detail}"


def _crawl_task_exception_outcome(exc: BaseException) -> CrawlOutcomeCode:
    if isinstance(exc, CrawlShutdownError):
        return CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR
    if isinstance(exc, CrawlMaxAgeExceededError):
        return CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED
    return CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR


def _crawl_task_exception_message(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = f"{type(exc).__name__} while running crawl"
    return message[:512]


def _crawl_queue_enqueue_failure_message(exc: BaseException) -> str:
    message = str(exc).strip()
    if not message:
        message = type(exc).__name__
    return f"Failed to add crawl to pending queue: {message}"[:512]


async def _record_crawl_task_exception(
    *,
    job_id: UUID,
    run_id: UUID,
    exc: BaseException,
) -> None:
    from intric.main.models import Status as JobStatus

    outcome_code = _crawl_task_exception_outcome(exc)
    error_message = _crawl_task_exception_message(exc)
    now = datetime.now(timezone.utc)

    async with Container.session_scope() as session:
        await commit_terminal(
            session,
            TerminalEvent(
                crawl_run_id=run_id,
                job_id=job_id,
                job_status=JobStatus.FAILED,
                outcome_code=outcome_code,
                finished_at=now,
                result_location=error_message,
                only_set_crawl_outcome_if_missing=True,
            ),
        )


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
                    assert user is not None
                    cast(Any, container.user).override(providers.Object(user))
                    cast(Any, container.tenant).override(providers.Object(user.tenant))

                    # Feeder mode: Create crawl run AND job record, then add to pending queue
                    # Why: Pre-create DB records so feeder only handles ARQ enqueueing
                    # Deterministic job_id based on run_id prevents duplicate enqueues
                    if settings.crawl_feeder_enabled and redis_client:
                        from intric.jobs.job_models import Job, Task
                        from intric.main.models import Status
                        from intric.websites.domain.crawl_run import CrawlRun

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
                        job_data: CrawlPendingJobData = {
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

                        # Step 5: Add to pending queue with orphaning protection.
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
                            failure_message = _crawl_queue_enqueue_failure_message(
                                redis_exc
                            )
                            # Redis push failed; commit one terminal event so the UI
                            # has a typed reason and no orphaned job remains.
                            try:
                                await commit_terminal(
                                    website_session,
                                    TerminalEvent(
                                        crawl_run_id=crawl_run.id,
                                        job_id=job_in_db.id,
                                        job_status=Status.FAILED,
                                        outcome_code=(
                                            CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED
                                        ),
                                        finished_at=datetime.now(timezone.utc),
                                        result_location=failure_message,
                                    ),
                                )
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
                                failure_message,
                                extra={
                                    "website_id": str(website.id),
                                    "url": website.url,
                                    "job_id": str(job_in_db.id),
                                },
                            )
                    else:
                        # Direct enqueue mode (original behavior when feeder disabled)
                        from intric.websites.domain.website import Website

                        crawl_service = container.crawl_service()
                        await crawl_service.crawl(cast(Website, website))
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
    job_id = UUID(str(job_id))
    # Create TaskManager directly without using container.task_manager()
    # Why: container.task_manager() tries to resolve job_service which has
    # transitive dependency: job_service → job_repo → session
    # With sessionless container (session=None), this fails type validation.
    #
    # This is safe because:
    # 1. crawl_task acknowledges crawler-owned terminal commits on TaskManager
    # 2. Status updates use execute_with_recovery() with its own sessions
    # 3. fail_job() has fallback to direct SQL when job_service is None
    #    (ensures jobs are marked failed even when exceptions occur early)
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
    session_holder: SessionHolder = {"session": None, "uploader": None}

    try:
        redis_client = container.redis_client()
    except Exception as exc:
        logger.warning(
            "Failed to resolve Redis before tenant injection",
            extra={"job_id": str(job_id), "error": str(exc)},
        )

    # Read the feeder pre-acquire flag before tenant injection so the finally
    # release path can still repair capacity if tenant resolution fails.
    slot_acquire = await acquire_crawl_slot(
        CrawlSlotAcquireRequest(
            job_id=job_id,
            tenant_id=None,
            preacquired_tenant_id=None,
            semaphore_ttl_seconds=settings.tenant_worker_semaphore_ttl_seconds,
        ),
        limiter=None,
        redis_client=redis_client,
    )
    preacquired_tenant_id = slot_acquire.preacquired_tenant_id

    try:
        tenant = container.tenant()
    except Exception:  # pragma: no cover - defensive guard when tenant not injected
        tenant = None

    tenant_crawler_settings = TenantCrawlerSettings.from_overrides(
        tenant.crawler_settings
        if tenant is not None and hasattr(tenant, "crawler_settings")
        else None
    )
    if tenant is not None:
        tenant_crawler_settings.warn_invalid_overrides(
            logger,
            tenant_id=tenant.id,
            website_id=params.website_id,
        )

    if tenant:
        limiter = container.tenant_concurrency_limiter()
        semaphore_ttl = get_crawler_setting(
            "tenant_worker_semaphore_ttl_seconds",
            tenant_crawler_settings,
            default=settings.tenant_worker_semaphore_ttl_seconds,
        )
        slot_acquire = await acquire_crawl_slot(
            CrawlSlotAcquireRequest(
                job_id=job_id,
                tenant_id=tenant.id,
                preacquired_tenant_id=preacquired_tenant_id,
                semaphore_ttl_seconds=semaphore_ttl,
            ),
            limiter=limiter,
            redis_client=redis_client,
        )
        acquired = slot_acquire.acquired
        preacquired_tenant_id = slot_acquire.preacquired_tenant_id

        if not acquired:
            # Enforce max age limit with exponential backoff to prevent infinite retry loops.
            # Concurrency limit (busy signal) is NOT counted as a failure - only age is checked.
            # This prevents jobs from being abandoned just because they're waiting for a slot.

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
                failure_message = (
                    f"Crawl job {job_id} abandoned after {job_age:.0f}s "
                    f"(max: {max_age_seconds}s) - still waiting for concurrency slot"
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
                raise CrawlMaxAgeExceededError(failure_message)

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
                    from intric.main.models import Status

                    skip_message = (
                        f"Skipped duplicate crawl; active job {primary_job_id}"
                    )
                    result = await commit_terminal(
                        session,
                        TerminalEvent(
                            crawl_run_id=params.run_id,
                            job_id=job_id,
                            job_status=Status.FAILED,
                            outcome_code=CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
                            finished_at=datetime.now(timezone.utc),
                            result_location=skip_message,
                        ),
                    )
                    if result.job_rows_updated == 0:
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
                task_manager.acknowledge_terminal_commit(successful=True)
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
        async def _on_crawl_task_exception(exc: BaseException) -> None:
            await _record_crawl_task_exception(
                job_id=job_id,
                run_id=params.run_id,
                exc=exc,
            )

        async with task_manager.set_status_on_exception(
            status_already_set=True,
            on_exception=_on_crawl_task_exception,
        ):
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

            start = time.time()
            if tenant is None:
                raise RuntimeError("Crawler tenant context is required")

            bootstrap_result = await bootstrap_crawl(
                session_scope=Container.session_scope,
                website_id=params.website_id,
                tenant=tenant,
                user=container.user(),
                tenant_crawler_settings=tenant_crawler_settings,
                settings=settings,
                http_auth_password_decrypter=lambda encrypted_password: (
                    container.http_auth_encryption_service().decrypt_password(
                        encrypted_password
                    )
                ),
            )

            crawl_context = bootstrap_result.crawl_context
            embedding_model_spec = bootstrap_result.embedding_model
            existing_titles = bootstrap_result.existing_titles
            existing_blob_state_by_title = bootstrap_result.existing_blob_state_by_title
            website_url = bootstrap_result.website_url
            website_name = bootstrap_result.website_name
            website_owner_id = bootstrap_result.website_owner_id
            website_last_source_verified_at = (
                bootstrap_result.website_last_source_verified_at
            )

            timings["fetch_existing_titles"] = time.time() - start

            logger.info(
                "Crawl bootstrap phase complete",
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
            num_hash_retained_pages = 0
            num_hash_retained_files = 0
            num_source_retained_pages = 0
            num_files_too_large_skipped = 0

            # Aggregate failure reasons across all batches
            failure_counts: dict[FailureReason, int] = defaultdict(int)

            # Use set for O(1) membership tests
            must_keep_titles: set[str] = set()
            failed_titles: set[str] = set()  # Failed URLs excluded from stale deletion

            # Get per-tenant settings for heartbeat BEFORE starting crawl
            # This ensures heartbeat runs during the entire crawl phase
            heartbeat_interval_seconds = get_crawler_setting(
                "crawl_heartbeat_interval_seconds",
                tenant_crawler_settings,
                default=settings.crawl_heartbeat_interval_seconds,
            )
            semaphore_ttl_seconds = get_crawler_setting(
                "tenant_worker_semaphore_ttl_seconds",
                tenant_crawler_settings,
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

            http_cache_dir: Path | None = None
            if settings.crawl_http_cache_enabled:
                candidate_cache_dir = _build_http_cache_dir(
                    root_dir=settings.crawl_http_cache_dir,
                    tenant_id=crawl_context.tenant_id,
                    website_id=params.website_id,
                )
                try:
                    candidate_cache_dir.mkdir(parents=True, exist_ok=True)
                    _prune_http_cache_dir(
                        candidate_cache_dir,
                        max_bytes=settings.crawl_http_cache_max_bytes_per_website,
                    )
                    http_cache_dir = candidate_cache_dir
                    logger.info(
                        "Scrapy HTTP cache enabled for crawl",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "cache_dir": str(http_cache_dir),
                            "policy": "RFC2616Policy",
                        },
                    )
                except OSError as cache_error:
                    logger.warning(
                        "Scrapy HTTP cache disabled because cache directory is unavailable",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "cache_dir": str(candidate_cache_dir),
                            "error": str(cache_error),
                        },
                    )

            sitemap_lastmod_skip_cutoff: datetime | None = None
            sitemap_lastmod_skip_allowed_urls: frozenset[str] = frozenset()
            if _should_enable_sitemap_lastmod_skip(
                crawl_type=params.crawl_type,
                website_last_source_verified_at=website_last_source_verified_at,
                tenant_crawler_settings=tenant_crawler_settings,
            ):
                assert website_last_source_verified_at is not None
                sitemap_lastmod_skip_allowed_urls = _build_sitemap_lastmod_skip_urls(
                    existing_blob_state_by_title=existing_blob_state_by_title,
                    embedding_model_id=crawl_context.embedding_model_id,
                )
                if sitemap_lastmod_skip_allowed_urls:
                    sitemap_lastmod_skip_cutoff = website_last_source_verified_at
                    logger.info(
                        "Sitemap lastmod source skip enabled for crawl",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "skip_candidate_count": len(
                                sitemap_lastmod_skip_allowed_urls
                            ),
                            "last_source_verified_at": (
                                website_last_source_verified_at.isoformat()
                            ),
                        },
                    )

            # Use Scrapy crawler to process website content
            # Measure crawl and parse phase
            start = time.time()
            async with crawler.crawl(
                url=params.url,
                download_files=params.download_files,
                crawl_type=params.crawl_type,
                http_user=crawl_context.http_auth_user or "",  # From bootstrap DTO
                http_pass=crawl_context.http_auth_pass or "",  # From bootstrap DTO
                # Pass tenant settings for tenant-aware Scrapy configuration
                tenant_crawler_settings=tenant_crawler_settings,
                http_cache_dir=http_cache_dir,
                sitemap_lastmod_skip_cutoff=sitemap_lastmod_skip_cutoff,
                sitemap_lastmod_skip_allowed_urls=sitemap_lastmod_skip_allowed_urls,
                # Pass heartbeat callback for liveness during Scrapy crawl phase
                heartbeat_callback=heartbeat_monitor.tick,
                heartbeat_interval=float(heartbeat_interval_seconds),
            ) as crawl:
                timings["crawl_and_parse"] = time.time() - start

                # Track partial completion status for logging
                crawl_is_partial = crawl.is_partial
                crawl_termination_reason: CrawlTerminationReason = (
                    crawl.termination_reason
                )
                num_files_too_large_skipped = (
                    crawl.diagnostics.files_too_large_skipped_count
                )
                # Page/file failures cannot exist before processing; this call only
                # classifies crawler-level terminal conditions that must skip cleanup.
                crawl_output_outcome_code = classify_crawl_outcome(
                    crawl_type=_crawl_type_for_outcome(params.crawl_type),
                    is_partial=crawl_is_partial,
                    termination_reason=crawl_termination_reason,
                    pages_count=crawl.pages_count,
                    files_too_large_skipped=num_files_too_large_skipped,
                    source_retained_count=crawl.source_retained_count,
                    failure_summary=None,
                    pages_failed=0,
                    files_failed=0,
                )
                terminal_failure_message = _terminal_zero_output_message(
                    crawl_output_outcome_code,
                    crawl.diagnostics,
                )
                if terminal_failure_message is not None:
                    assert crawl_output_outcome_code is not None
                    terminal_outcome_code = crawl_output_outcome_code
                    from intric.main.models import Status as JobStatus

                    logger.warning(
                        "Crawl produced no usable output",
                        extra={
                            "job_id": str(job_id),
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "crawl_type": params.crawl_type.value,
                            "outcome_code": terminal_outcome_code.value,
                            "termination_reason": crawl_termination_reason,
                            "scrapy_diagnostics": crawl.diagnostics.to_log_fields(),
                        },
                    )

                    terminal_finished_at = datetime.now(timezone.utc)

                    async def _do_terminal_zero_output_commit(
                        sess: AsyncSession,
                    ) -> None:
                        await commit_terminal(
                            sess,
                            TerminalEvent(
                                crawl_run_id=params.run_id,
                                job_id=job_id,
                                job_status=JobStatus.FAILED,
                                outcome_code=terminal_outcome_code,
                                finished_at=terminal_finished_at,
                                result_location=terminal_failure_message,
                                crawl_run_update=CrawlRunTerminalUpdate(
                                    pages_crawled=0,
                                    files_downloaded=0,
                                    pages_failed=0,
                                    files_failed=0,
                                    pages_source_retained=0,
                                    pages_hash_retained=0,
                                    files_hash_retained=0,
                                    files_too_large_skipped=num_files_too_large_skipped,
                                    failure_summary=None,
                                ),
                            ),
                        )

                    await execute_with_recovery(
                        session_holder=session_holder,
                        created_sessions=created_sessions,
                        operation_name="terminal_zero_output_commit",
                        operation=_do_terminal_zero_output_commit,
                    )

                    await apply_post_terminal_effects(
                        PostTerminalEffectInput(
                            recovery=PostTerminalRecoveryContext(
                                session_holder=session_holder,
                                created_sessions=created_sessions,
                                execute_with_recovery=execute_with_recovery,
                            ),
                            audit_service=container.audit_service(),
                            audit_payload=CrawlAuditPayload(
                                tenant_id=crawl_context.tenant_id,
                                website_id=params.website_id,
                                website_url=website_url,
                                website_name=website_name,
                                website_owner_id=website_owner_id,
                                pages_crawled=0,
                                pages_failed=0,
                                pages_hash_retained=0,
                                pages_source_retained=0,
                                files_downloaded=0,
                                files_failed=0,
                                files_hash_retained=0,
                                files_too_large_skipped=num_files_too_large_skipped,
                                blobs_deleted=0,
                                successful=False,
                                outcome_code=terminal_outcome_code,
                            ),
                            circuit_breaker_operation_name=(
                                "terminal_circuit_breaker_update"
                            ),
                        )
                    )

                    # Terminal zero-output crawls advance no website crawl
                    # timestamps, so scheduled retries are not hidden.
                    task_manager.acknowledge_terminal_commit(successful=False)
                    return {
                        "status": "failed",
                        "outcome_code": terminal_outcome_code.value,
                    }

                if crawl_is_partial:
                    logger.warning(
                        "Crawl timed out but has partial results",
                        extra={
                            "job_id": str(job_id),
                            "website_id": str(params.website_id),
                            "url": params.url,
                            "pages_collected": crawl.pages_count,
                            "source_retained_count": crawl.source_retained_count,
                            "termination_reason": crawl_termination_reason,
                            "stale_cleanup": "skipped_for_partial_crawl",
                        },
                    )

                # Measure page processing time
                process_start = time.time()
                if crawl.source_retained_urls:
                    logger.warning(
                        "Retained sitemap URLs without fetching due to lastmod",
                        extra={
                            "reason": "sitemap_lastmod_source_skip_applied",
                            "job_id": str(job_id),
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "lastmod_cutoff": sitemap_lastmod_skip_cutoff.isoformat()
                            if sitemap_lastmod_skip_cutoff is not None
                            else None,
                            "retained_count": crawl.source_retained_count,
                            "caveat": "Trusts upstream sitemap lastmod values",
                        },
                    )

                async def _persist_pages(
                    page_buffer: list[CrawlPageData],
                ) -> PersistBatchResult:
                    return await persist_batch(
                        page_buffer=page_buffer,
                        ctx=crawl_context,
                        embedding_model=embedding_model_spec,
                        container=container,
                        existing_blob_state_by_title=existing_blob_state_by_title,
                    )

                page_processing_result = await process_pages(
                    pages=crawl.pages,
                    source_retained_urls=crawl.source_retained_urls,
                    batch_size=crawl_context.batch_size,
                    heartbeat_tick=heartbeat_monitor.tick,
                    persist_pages=_persist_pages,
                )

                if isinstance(
                    page_processing_result, HeartbeatFailedPageProcessingAbort
                ):
                    return {
                        "status": "heartbeat_failed",
                        "pages_crawled": page_processing_result.pages_crawled,
                        "consecutive_failures": (
                            page_processing_result.consecutive_failures
                        ),
                    }

                if isinstance(page_processing_result, PreemptedPageProcessingAbort):
                    logger.warning(
                        "Detected job preemption during heartbeat",
                        extra={
                            "job_id": str(job_id),
                            "website_id": str(params.website_id),
                            "pages_processed": page_processing_result.pages_crawled,
                        },
                    )
                    return {
                        "status": "preempted_during_crawl",
                        "pages_crawled": page_processing_result.pages_crawled,
                    }

                assert isinstance(page_processing_result, PageProcessingSuccess)
                num_pages = page_processing_result.pages_crawled
                num_failed_pages = page_processing_result.pages_failed
                num_hash_retained_pages = page_processing_result.pages_hash_retained
                num_source_retained_pages = page_processing_result.pages_source_retained
                must_keep_titles.update(page_processing_result.cleanup_protected_titles)
                failed_titles.update(page_processing_result.failed_titles)
                for reason, count in page_processing_result.failure_counts.items():
                    failure_counts[reason] += count

                logger.debug(
                    "Processed crawl pages",
                    extra={
                        "job_id": str(job_id),
                        "pages_crawled": num_pages,
                        "pages_persisted": page_processing_result.pages_persisted,
                        "pages_retained": num_hash_retained_pages,
                        "pages_failed": num_failed_pages,
                    },
                )

                timings["process_pages"] = time.time() - process_start

                file_start = time.time()

                async def _process_changed_file(
                    file: Path,
                    filename: str,
                    content_hash: bytes,
                ) -> None:
                    async def _process_single_file(sess: AsyncSession) -> None:
                        session_provider = cast(Any, container.session)
                        session_provider.override(providers.Object(sess))
                        file_uploader = container.text_processor()
                        embedding_model_repo = container.embedding_model_repo2()
                        embedding_model_id = crawl_context.embedding_model_id
                        if embedding_model_id is None:
                            raise RuntimeError(
                                "Changed-file processing requires an embedding model"
                            )
                        file_embedding_model = await embedding_model_repo.one(
                            embedding_model_id
                        )
                        await file_uploader.process_file(
                            filepath=file,
                            filename=filename,
                            website_id=params.website_id,
                            embedding_model=file_embedding_model,
                            content_hash=content_hash,
                        )

                    await execute_with_recovery(
                        session_holder=session_holder,
                        created_sessions=created_sessions,
                        operation_name=f"process_file_{filename}",
                        operation=_process_single_file,
                    )

                def _record_file_processing_error(
                    _file: Path,
                    filename: str,
                    exc: Exception,
                ) -> None:
                    logger.error(
                        "Exception while uploading file",
                        extra={
                            "website_id": str(params.website_id),
                            "tenant_id": str(crawl_context.tenant_id),
                            "crawled_filename": filename,
                            "embedding_model": crawl_context.embedding_model_name,
                        },
                        exc_info=exc,
                    )

                file_processing_result = await process_files(
                    files=crawl.files,
                    existing_blob_state_by_title=existing_blob_state_by_title,
                    embedding_model_id=crawl_context.embedding_model_id,
                    process_changed_file=_process_changed_file,
                    record_file_processing_error=_record_file_processing_error,
                )
                num_files = file_processing_result.files_downloaded
                num_failed_files = file_processing_result.files_failed
                num_hash_retained_files = file_processing_result.files_hash_retained
                must_keep_titles.update(file_processing_result.cleanup_protected_titles)
                failed_titles.update(file_processing_result.failed_titles)
                timings["process_files"] = time.time() - file_start

            # Cleanup phase: delete stale blobs (batch for performance)
            cleanup_start = time.time()
            # Exclude failed_titles - their original data was preserved by transaction rollback
            # Crawler-level outcome is the cleanup signal; final outcome classification
            # happens after cleanup and includes persistence/file processing failures.
            cleanup_policy = cleanup_policy_for_outcome(crawl_output_outcome_code)

            async def _delete_stale_titles(titles: Sequence[str]) -> int:
                titles_to_delete = list(titles)

                async def _do_stale_blob_cleanup(sess: AsyncSession) -> int:
                    session_provider = cast(Any, container.session)
                    session_provider.override(providers.Object(sess))
                    cleanup_repo = container.info_blob_repo()
                    return await cleanup_repo.batch_delete_by_titles_and_website(
                        titles=titles_to_delete,
                        website_id=params.website_id,
                        tenant_id=crawl_context.tenant_id,
                    )

                return await execute_with_recovery(
                    session_holder=session_holder,
                    created_sessions=created_sessions,
                    operation_name="stale_blob_cleanup",
                    operation=_do_stale_blob_cleanup,
                )

            cleanup_result = await cleanup_stale_blobs(
                existing_titles=existing_titles,
                must_keep_titles=must_keep_titles,
                failed_titles=failed_titles,
                cleanup_policy=cleanup_policy,
                delete_stale_titles=_delete_stale_titles,
            )
            num_deleted_blobs = cleanup_result.deleted_count
            if num_deleted_blobs > 0:
                logger.info(
                    f"Batch deleted {num_deleted_blobs} stale blobs",
                    extra={
                        "website_id": str(params.website_id),
                        "num_stale": len(cleanup_result.stale_titles),
                        "num_deleted": num_deleted_blobs,
                    },
                )
            timings["cleanup_deleted"] = time.time() - cleanup_start

            # Measure website size update with recovery wrapper
            update_start = time.time()

            async def _do_update_size(sess: AsyncSession) -> None:
                # Session provided by execute_with_recovery (session-per-operation pattern)
                # NOTE: Use crawl_context primitives, NOT detached ORM website object
                from intric.database.tables.info_blobs_table import (
                    InfoBlobs as InfoBlobsTable,
                )
                from intric.database.tables.websites_table import (
                    Websites as WebsitesTable,
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
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="website_size_update",
                operation=_do_update_size,
            )
            timings["update_size"] = time.time() - update_start

            async def _do_timestamp_update(sess: AsyncSession) -> None:
                await update_website_timestamps_after_crawl(
                    sess,
                    website_id=params.website_id,
                    tenant_id=crawl_context.tenant_id,
                    crawl_type=params.crawl_type,
                    crawl_is_partial=crawl_is_partial,
                    pages_failed=num_failed_pages,
                    files_failed=num_failed_files,
                )

            await execute_with_recovery(
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="website_post_crawl_timestamps_update",
                operation=_do_timestamp_update,
            )

            _warn_if_retained_items_without_embedding_config(
                embedding_model=embedding_model_spec,
                retained_pages=num_hash_retained_pages,
                retained_files=num_hash_retained_files,
                website_id=params.website_id,
                tenant_id=crawl_context.tenant_id,
            )

            # Calculate skip rates for performance analysis
            total_page_source_count = num_pages + num_source_retained_pages
            total_retained_pages = num_hash_retained_pages + num_source_retained_pages
            page_skip_rate = (
                (total_retained_pages / total_page_source_count * 100)
                if total_page_source_count > 0
                else 0
            )
            total_file_source_count = num_files + num_files_too_large_skipped
            file_skip_rate = (
                (
                    (num_hash_retained_files + num_files_too_large_skipped)
                    / total_file_source_count
                    * 100
                )
                if total_file_source_count > 0
                else 0
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
                f"Pages:   {num_pages} fetched, {num_source_retained_pages} source-retained, {num_failed_pages} failed, {num_hash_retained_pages} hash-retained ({page_skip_rate:.1f}% retained)",
                f"Files:   {num_files} downloaded, {num_failed_files} failed, {num_hash_retained_files} hash-retained, {num_files_too_large_skipped} too-large skipped ({file_skip_rate:.1f}%)",
                f"Cleanup: {num_deleted_blobs} stale entries removed",
            ]
            if crawl_is_partial:
                summary.append(f"Partial completion due to: {crawl_termination_reason}")
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
                    "pages_source_retained": num_source_retained_pages,
                    "pages_failed": num_failed_pages,
                    "pages_hash_retained": num_hash_retained_pages,
                    "page_skip_rate_percent": page_skip_rate,
                    "files_crawled": num_files,
                    "files_failed": num_failed_files,
                    "files_hash_retained": num_hash_retained_files,
                    "files_too_large_skipped": num_files_too_large_skipped,
                    "file_skip_rate_percent": file_skip_rate,
                    "blobs_deleted": num_deleted_blobs,
                },
            )

            # Preemption check: Verify job wasn't marked FAILED while we were crawling.
            # If preempted, don't write results - a new crawl is already running.
            from intric.database.tables.job_table import Jobs
            from intric.main.models import Status as JobStatus

            async def _do_suicide_check(sess: AsyncSession) -> str | None:
                # Session provided by execute_with_recovery (session-per-operation pattern)
                result = await sess.execute(
                    sa.select(Jobs.status).where(Jobs.id == job_id)
                )
                return result.scalar_one_or_none()

            job_status_value = await execute_with_recovery(
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

            failure_summary = dict(failure_counts) if failure_counts else None
            crawl_run_outcome_code = classify_crawl_outcome(
                crawl_type=_crawl_type_for_outcome(params.crawl_type),
                is_partial=crawl_is_partial,
                termination_reason=crawl_termination_reason,
                pages_count=num_pages,
                files_count=num_files,
                source_retained_count=num_source_retained_pages,
                pages_hash_retained=num_hash_retained_pages,
                files_hash_retained=num_hash_retained_files,
                files_too_large_skipped=num_files_too_large_skipped,
                failure_summary=failure_summary,
                pages_failed=num_failed_pages,
                files_failed=num_failed_files,
            )

            task_manager.result_location = (
                f"/api/v1/websites/{params.website_id}/info-blobs/"
            )
            terminal_finished_at = datetime.now(timezone.utc)

            async def _do_terminal_completion_commit(sess: AsyncSession) -> None:
                from intric.main.models import Status as JobStatus

                await commit_terminal(
                    sess,
                    TerminalEvent(
                        crawl_run_id=params.run_id,
                        job_id=job_id,
                        job_status=JobStatus.COMPLETE,
                        outcome_code=crawl_run_outcome_code,
                        finished_at=terminal_finished_at,
                        result_location=task_manager.result_location,
                        crawl_run_update=CrawlRunTerminalUpdate(
                            pages_crawled=num_pages,
                            files_downloaded=num_files,
                            pages_failed=num_failed_pages,
                            files_failed=num_failed_files,
                            pages_source_retained=num_source_retained_pages,
                            pages_hash_retained=num_hash_retained_pages,
                            files_hash_retained=num_hash_retained_files,
                            files_too_large_skipped=num_files_too_large_skipped,
                            failure_summary=failure_summary,
                        ),
                    ),
                )

                logger.debug(
                    "Job completed via terminal commit",
                    extra={"job_id": str(job_id)},
                )

            await execute_with_recovery(
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="terminal_completion_commit",
                operation=_do_terminal_completion_commit,
            )

            task_manager.acknowledge_terminal_commit(successful=True)

            total_items = num_pages + num_files + num_source_retained_pages
            total_failed = num_failed_pages + num_failed_files
            crawl_successful = total_items > 0 and total_failed < total_items

            await apply_post_terminal_effects(
                PostTerminalEffectInput(
                    recovery=PostTerminalRecoveryContext(
                        session_holder=session_holder,
                        created_sessions=created_sessions,
                        execute_with_recovery=execute_with_recovery,
                    ),
                    audit_service=container.audit_service(),
                    audit_payload=CrawlAuditPayload(
                        tenant_id=crawl_context.tenant_id,
                        website_id=params.website_id,
                        website_url=website_url,
                        website_name=website_name,
                        website_owner_id=website_owner_id,
                        pages_crawled=num_pages,
                        pages_failed=num_failed_pages,
                        pages_hash_retained=num_hash_retained_pages,
                        pages_source_retained=num_source_retained_pages,
                        files_downloaded=num_files,
                        files_failed=num_failed_files,
                        files_hash_retained=num_hash_retained_files,
                        files_too_large_skipped=num_files_too_large_skipped,
                        blobs_deleted=num_deleted_blobs,
                        successful=crawl_successful,
                        outcome_code=crawl_run_outcome_code,
                    ),
                    circuit_breaker_operation_name="circuit_breaker_update",
                )
            )

        return task_manager.successful()
    except Retry:
        raise
    except CrawlShutdownError as exc:
        try:
            await _record_crawl_task_exception(
                job_id=job_id,
                run_id=params.run_id,
                exc=exc,
            )
        except Exception as outcome_exc:
            logger.warning(
                "Failed to record crawl shutdown outcome code after crawl exception",
                extra={
                    "job_id": str(job_id),
                    "run_id": str(params.run_id),
                    "outcome_code": _crawl_task_exception_outcome(exc).value,
                    "error": str(outcome_exc),
                },
            )
        raise
    except Exception as exc:
        try:
            await _record_crawl_task_exception(
                job_id=job_id,
                run_id=params.run_id,
                exc=exc,
            )
        except Exception as outcome_exc:
            logger.warning(
                "Failed to record crawl outcome code after crawl exception",
                extra={
                    "job_id": str(job_id),
                    "run_id": str(params.run_id),
                    "outcome_code": _crawl_task_exception_outcome(exc).value,
                    "error": str(outcome_exc),
                },
            )
        raise
    finally:
        terminal_redis_client = redis_client
        if terminal_redis_client is None:
            try:
                terminal_redis_client = container.redis_client()
            except Exception as redis_exc:
                logger.debug(
                    "Could not resolve Redis client for crawl task terminal cleanup",
                    extra={"job_id": str(job_id), "error": str(redis_exc)},
                )

        slot_release = await release_crawl_slot_after_task(
            CrawlSlotReleaseRequest(
                job_id=job_id,
                tenant_id=tenant.id if tenant is not None else None,
                preacquired_tenant_id=preacquired_tenant_id,
                acquired=acquired,
            ),
            limiter=limiter,
            redis_client=terminal_redis_client,
            settings=settings,
        )
        logger.debug(
            "Crawl slot terminal release completed",
            extra={
                "job_id": str(job_id),
                "tenant_id": str(tenant.id) if tenant is not None else None,
                "preacquired_tenant_id": str(preacquired_tenant_id)
                if preacquired_tenant_id is not None
                else None,
                "slot_release_path": slot_release.path.value,
                "slot_released": slot_release.released,
            },
        )

        # Cleanup Redis retry counters to prevent memory leak
        if terminal_redis_client and job_id:
            try:
                await terminal_redis_client.delete(
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
