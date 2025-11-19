import asyncio
import hashlib
import random
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from arq import Retry
from dependency_injector import providers
import redis.asyncio as aioredis
import sqlalchemy as sa

from intric.main.container.container import Container
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.main.config import SETTINGS
from intric.tenants.crawler_settings_helper import get_crawler_setting
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlTask,
)
# Note: Only using hashlib for file content hashing (works reliably)
# Page content hashing removed due to dynamic content (timestamps, etc.)

logger = get_logger(__name__)

_BACKOFF_JITTER_RATIO = 0.25


def _calculate_exponential_backoff(
    attempt: int,
    base_delay: float,
    max_delay: float,
) -> float:
    """Calculate exponential backoff delay with full jitter.

    Uses true exponential backoff: delay = min(max_delay, base * 2^(attempt-1))
    Then applies full jitter: random.uniform(0, delay)

    Args:
        attempt: Current attempt number (1-indexed, where 1 = first retry)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap in seconds

    Returns:
        Delay in seconds with full jitter applied

    Examples:
        attempt=1, base=60, max=300 -> ~0-60s
        attempt=2, base=60, max=300 -> ~0-120s
        attempt=3, base=60, max=300 -> ~0-240s
        attempt=4, base=60, max=300 -> ~0-300s (capped)
    """
    # True exponential: 2^(attempt-1)
    # attempt=1 -> 2^0=1, attempt=2 -> 2^1=2, attempt=3 -> 2^2=4
    exp_delay = base_delay * (2 ** (attempt - 1))

    # Cap at max_delay
    capped_delay = min(exp_delay, max_delay)

    # Full jitter: random between 0 and capped_delay
    # This prevents synchronized retries (thundering herd)
    return random.uniform(0, capped_delay)


async def _reset_tenant_retry_delay(
    *, tenant_id: UUID, redis_client: aioredis.Redis | None
) -> None:
    if not redis_client:
        return

    key = f"tenant:{tenant_id}:limiter_backoff"
    try:
        await redis_client.delete(key)
    except Exception:  # pragma: no cover - best effort cleanup
        logger.debug(
            "Failed to reset tenant backoff counter",
            extra={"tenant_id": str(tenant_id)},
        )


async def _update_job_retry_stats(
    *,
    job_id: UUID,
    redis_client: aioredis.Redis | None,
    is_actual_failure: bool,
    max_age_seconds: int,
) -> tuple[int, float]:
    """Update job retry statistics using Redis Pipeline.

    CRITICAL: Only increments failure counter for ACTUAL failures, not concurrency busy signals.
    This prevents jobs from being abandoned just because they're waiting for an available slot.

    Uses Redis Pipeline for atomic-ish operations:
    1. SET NX for start_time (only sets if not exists, captures first attempt time)
    2. INCR retry_count ONLY if is_actual_failure=True (not for busy waits)
    3. GET both values to return current state

    Args:
        job_id: Unique job identifier
        redis_client: Redis connection
        is_actual_failure: True if this is a real failure (network error, etc.),
                          False if just waiting for concurrency slot (busy signal)
        max_age_seconds: Maximum job age for TTL calculation

    Returns:
        Tuple of (retry_attempt_count, job_age_seconds)
        - retry_attempt_count: Number of actual failures (0 if only busy waits)
        - job_age_seconds: Age since first attempt in seconds

    Example:
        Job tries to run at 2:00:00 but hits concurrency limit:
        - is_actual_failure=False → retry_count stays 0, only max_age enforced

        Job tries to crawl but gets network timeout:
        - is_actual_failure=True → retry_count increments, both limits enforced
    """
    if not redis_client:
        # Graceful degradation: no Redis means no tracking
        return 0, 0.0

    now = time.time()
    ttl_seconds = max_age_seconds + 3600  # Buffer to prevent premature expiry

    start_key = f"job:{job_id}:start_time"
    count_key = f"job:{job_id}:retry_count"

    try:
        # Use Pipeline for network efficiency (not strict atomicity, but good enough)
        async with redis_client.pipeline(transaction=True) as pipe:
            # 1. Set start time ONLY if it doesn't exist (NX flag)
            #    This ensures we always track from the FIRST attempt
            pipe.set(start_key, str(now), nx=True, ex=ttl_seconds)

            # 2. Get current start time
            pipe.get(start_key)

            # 3. Conditionally increment failure counter
            #    CRITICAL: Only increment for ACTUAL failures, not busy waits
            if is_actual_failure:
                pipe.incr(count_key)
                pipe.expire(count_key, ttl_seconds)
            else:
                pipe.get(count_key)  # Just read current value

            results = await pipe.execute()

        # Parse results
        # results[0] = True/False (whether SET succeeded)
        # results[1] = start_time (bytes)
        # results[2] = retry_count (int if incr, bytes if get)

        start_time_bytes = results[1]
        retry_count_val = results[2]

        # Decode Redis bytes to Python types
        start_ts = float(start_time_bytes.decode()) if start_time_bytes else now

        if is_actual_failure:
            # INCR returns int
            retry_count = int(retry_count_val) if retry_count_val else 1
        else:
            # GET returns bytes or None
            retry_count = int(retry_count_val.decode()) if retry_count_val else 0

        age_seconds = now - start_ts
        return retry_count, age_seconds

    except Exception as exc:  # pragma: no cover - safety fallback
        logger.warning(
            "Failed to update job retry stats",
            extra={
                "job_id": str(job_id),
                "error": str(exc),
                "is_actual_failure": is_actual_failure,
            },
        )
        # Conservative fallback
        return 0, 0.0


async def process_page_with_retry(
    page,
    uploader,
    session,
    params,
    website,
    max_retries: int | None = None,
    retry_delay: float | None = None,
    tenant_slug: str | None = None,
) -> tuple[bool, str | None]:
    """Process a single page with retry logic.

    Args:
        page: CrawledPage object
        uploader: Text processor
        session: Database session
        params: CrawlTask parameters
        website: Website entity
        max_retries: Maximum retry attempts (defaults to SETTINGS.crawl_page_max_retries)
        retry_delay: Initial delay between retries in seconds (defaults to SETTINGS.crawl_page_retry_delay)

    Returns:
        Tuple of (success: bool, error_message: str | None)
    """
    if max_retries is None:
        max_retries = SETTINGS.crawl_page_max_retries
    if retry_delay is None:
        retry_delay = SETTINGS.crawl_page_retry_delay

    for attempt in range(max_retries):
        try:
            # Create explicit savepoint for proper transaction handling
            savepoint = await session.begin_nested()
            try:
                await uploader.process_text(
                    text=page.content,
                    title=page.url,
                    website_id=params.website_id,
                    url=page.url,
                    embedding_model=website.embedding_model,
                )
                await savepoint.commit()
                return True, None  # Success
            except Exception:
                await savepoint.rollback()
                raise  # Re-raise to trigger retry logic

        except Exception as e:
            if attempt < max_retries - 1:
                # Calculate exponential backoff: 1s, 2s, 4s
                delay = retry_delay * (2**attempt)
                logger.warning(
                    f"Failed to process page {page.url} (attempt {attempt + 1}/{max_retries}): {str(e)}. "
                    f"Retrying in {delay}s...",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                        "tenant_slug": tenant_slug,
                        "page_url": page.url,
                        "embedding_model": getattr(website.embedding_model, "name", None),
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                    },
                )
                await asyncio.sleep(delay)
            else:
                # Final attempt failed
                error_msg = f"Failed after {max_retries} attempts: {str(e)}"
                logger.error(
                    f"Permanently failed to process page {page.url}: {error_msg}",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                        "tenant_slug": tenant_slug,
                        "page_url": page.url,
                        "embedding_model": getattr(website.embedding_model, "name", None),
                        "attempts": max_retries,
                    },
                )
                return False, error_msg

    return False, "Unknown error"


async def _add_to_pending_queue(
    *,
    tenant_id: UUID,
    website_data: dict,
    redis_client: aioredis.Redis | None,
) -> bool:
    """Add a crawl job to the pending queue for feeder processing.

    Args:
        tenant_id: Tenant identifier
        website_data: Website crawl parameters as dict
        redis_client: Redis connection

    Returns:
        True if successfully added, False otherwise
    """
    if not redis_client:
        logger.error("Cannot add to pending queue: Redis client unavailable")
        return False

    import json

    key = f"tenant:{tenant_id}:crawl_pending"
    try:
        # Add to right side of list (FIFO queue)
        job_json = json.dumps(website_data, default=str, sort_keys=True)
        await redis_client.rpush(key, job_json)
        logger.debug(
            "Added crawl to pending queue",
            extra={
                "tenant_id": str(tenant_id),
                "website_id": website_data.get("website_id"),
                "url": website_data.get("url"),
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


async def queue_website_crawls(container: Container):
    """Queue websites for crawling based on their update intervals.

    Why: Uses centralized scheduler service for maintainable interval logic.
    Properly handles DAILY, EVERY_OTHER_DAY, and WEEKLY intervals.

    Phase 2 Enhancement: When feeder is enabled, adds to pending queue instead
    of direct ARQ enqueue to prevent burst overload.
    """
    user_repo = container.user_repo()
    crawl_scheduler_service = container.crawl_scheduler_service()
    settings = get_settings()

    # Get Redis client for feeder mode (if enabled)
    redis_client = None
    if settings.crawl_feeder_enabled:
        try:
            redis_client = container.redis_client()
        except Exception as exc:
            logger.error(
                f"Feeder enabled but Redis unavailable: {exc}. "
                "Falling back to direct enqueue mode."
            )

    async with container.session().begin():
        # Why: Use scheduler service instead of direct repo call for better abstraction
        websites = await crawl_scheduler_service.get_websites_due_for_crawl()

        logger.info(
            f"Processing {len(websites)} websites due for crawling",
            extra={
                "feeder_enabled": settings.crawl_feeder_enabled,
                "mode": "pending_queue" if settings.crawl_feeder_enabled else "direct_enqueue",
            },
        )

        successful_crawls = 0
        failed_crawls = 0

        for website in websites:
            try:
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
                    crawl_run = CrawlRun.create(website=website)
                    crawl_run = await crawl_run_repo.add(crawl_run=crawl_run)

                    # Step 2: Create job record in database
                    # Why: Pre-create so job_id is deterministic and available for feeder
                    job_repo = container.job_repo()
                    job = Job(
                        task=Task.CRAWL,
                        name=f"Crawl: {website.name}",
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
                        "job_id": str(job_in_db.id),  # Critical: Deterministic ID from DB
                        "user_id": str(website.user_id),
                        "website_id": str(website.id),
                        "run_id": str(crawl_run.id),
                        "url": website.url,
                        "download_files": website.download_files,
                        "crawl_type": website.crawl_type.value,
                    }

                    # Step 5: Add to pending queue with orphaning protection
                    # P0 FIX: If Redis push fails, mark DB records as FAILED
                    # Why: Prevents orphaned crawl_run/job records that never execute
                    try:
                        if not await _add_to_pending_queue(
                            tenant_id=user.tenant.id,
                            website_data=job_data,
                            redis_client=redis_client,
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

            except Exception as e:
                # Why: Individual website failures shouldn't stop the entire batch
                failed_crawls += 1
                logger.error(
                    f"Failed to queue crawl for {website.url}: {str(e)}",
                    extra={
                        "website_id": str(website.id),
                        "tenant_id": str(website.tenant_id),
                        "tenant_slug": user.tenant.slug if getattr(user, "tenant", None) else None,
                        "space_id": str(website.space_id),
                        "user_id": str(website.user_id),
                    },
                )
                continue

        logger.info(
            f"Crawl queueing completed: {successful_crawls} successful, {failed_crawls} failed"
        )

    return True


async def crawl_task(*, job_id: UUID, params: CrawlTask, container: Container):
    task_manager = container.task_manager(job_id=job_id)
    settings = get_settings()

    tenant = None
    limiter = None
    acquired = False
    redis_client: aioredis.Redis | None = None

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

        # FIX: Check if feeder pre-acquired the slot (eliminates race condition)
        # Why: Feeder atomically acquires slot before enqueueing to ARQ
        # Worker checks this flag to skip redundant acquire attempt
        slot_preacquired = False
        if redis_client:
            try:
                preacquired_key = f"job:{job_id}:slot_preacquired"
                preacquired = await redis_client.get(preacquired_key)
                if preacquired:
                    slot_preacquired = True
                    # Clean up the flag - slot is now "owned" by this worker
                    await redis_client.delete(preacquired_key)
                    logger.debug(
                        "Slot pre-acquired by feeder, skipping limiter.acquire()",
                        extra={"job_id": str(job_id), "tenant_id": str(tenant.id)},
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to check slot_preacquired flag",
                    extra={"job_id": str(job_id), "error": str(exc)},
                )

        if slot_preacquired:
            acquired = True  # Slot was pre-acquired by feeder
            # FIX: Refresh semaphore TTL - we now own this slot
            # Why: Normal acquire() refreshes TTL via Lua script. When we skip acquire,
            # we must manually refresh to prevent semaphore expiry during long queue times.
            try:
                concurrency_key = f"tenant:{tenant.id}:active_jobs"
                await redis_client.expire(
                    concurrency_key,
                    settings.tenant_worker_semaphore_ttl_seconds
                )
            except Exception:
                pass  # Best effort - slot is still valid
        else:
            acquired = await limiter.acquire(tenant.id)

        if not acquired:
            # ✅ CRITICAL FIX: Enforce max age limit with exponential backoff
            # to prevent infinite retry loops during burst crawl periods
            #
            # IMPORTANT: Concurrency limit (busy signal) is NOT counted as a failure.
            # We only enforce max_age here, not max_retries.
            # This prevents jobs from being abandoned just because they're waiting for a slot.

            # Get per-tenant max age setting (falls back to env default)
            tenant_crawler_settings = tenant.crawler_settings if tenant else None
            max_age_seconds = get_crawler_setting(
                "crawl_job_max_age_seconds",
                tenant_crawler_settings,
                default=settings.crawl_job_max_age_seconds,
            )

            # Update stats with is_actual_failure=False (this is a busy signal, not a real failure)
            failure_count, job_age = await _update_job_retry_stats(
                job_id=job_id,
                redis_client=redis_client,
                is_actual_failure=False,  # CRITICAL: Don't count busy waits as failures
                max_age_seconds=max_age_seconds,
            )

            # Check if max job age exceeded (ONLY age check for busy signals)
            if job_age > max_age_seconds:
                # P0 FIX: Update crawl_run status before abandoning job
                # Why: Prevents orphaned DB records and provides failure visibility
                try:
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

                # P1 FIX: Cleanup Redis counters to prevent memory leak
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

    try:
        async with task_manager.set_status_on_exception():
            # Initialize timing tracking for performance analysis
            timings = {
                "fetch_existing_titles": 0.0,
                "crawl_and_parse": 0.0,
                "process_pages": 0.0,
                "process_files": 0.0,
                "cleanup_deleted": 0.0,
                "update_size": 0.0,
            }

            # Get resources
            crawler = container.crawler()
            uploader = container.text_processor()
            crawl_run_repo = container.crawl_run_repo()

            # Get services
            info_blob_repo = container.info_blob_repo()
            update_website_size_service = container.update_website_size_service()
            website_service = container.website_crud_service()
            website = await website_service.get_website(params.website_id)
            session = container.session()

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

            # Do task
            logger.info(f"Running crawl with params: {params}")

            # Extract HTTP auth credentials if present
            http_user = None
            http_pass = None
            if website.http_auth:
                http_user = website.http_auth.username
                http_pass = website.http_auth.password
                logger.info(
                    "HTTP auth configured for website",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                    },
                )

            num_pages = 0
            num_files = 0
            num_failed_pages = 0
            num_failed_files = 0
            num_deleted_blobs = 0
            num_skipped_files = 0  # Files with unchanged content (hash match)

            # Check if auth was configured but decryption failed
            # Why: Fail-fast with clear error message instead of confusing 401 errors during crawl
            # If database has auth fields but domain object doesn't, decryption failed
            from intric.database.tables.websites_table import Websites as WebsitesTable

            website_db_check = await session.execute(
                sa.select(WebsitesTable.http_auth_username).where(
                    WebsitesTable.id == params.website_id
                )
            )
            has_auth_in_db = website_db_check.scalar() is not None

            if has_auth_in_db and website.http_auth is None:
                logger.error(
                    "Cannot crawl website: HTTP auth decryption failed. "
                    "Check encryption_key setting is correct.",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                    },
                )
                raise Exception(
                    f"HTTP auth decryption failed for website {params.website_id}. "
                    "Check encryption_key configuration."
                )

            # Fetch existing titles for stale detection and file hashes for skip optimization
            start = time.time()
            from intric.database.tables.info_blobs_table import InfoBlobs

            stmt = sa.select(InfoBlobs.title, InfoBlobs.content_hash).where(
                InfoBlobs.website_id == params.website_id
            )
            result = await session.execute(stmt)

            # Build lookups for O(1) operations
            existing_file_hashes = {}  # filename -> hash (for files only)
            existing_titles = []
            for title, hash_bytes in result:
                existing_titles.append(title)
                # Only store hashes for files (not URLs) - files have simple stems like "document.pdf"
                if hash_bytes is not None and not title.startswith("http"):
                    existing_file_hashes[title] = hash_bytes

            timings["fetch_existing_titles"] = time.time() - start

            # ✅ PERFORMANCE FIX: Use set instead of list for O(1) membership tests
            # This changes O(n²) to O(n) when checking "if title not in crawled_titles"
            crawled_titles = set()

            # Use Scrapy crawler to process website content
            # Measure crawl and parse phase
            start = time.time()
            async with crawler.crawl(
                url=params.url,
                download_files=params.download_files,
                crawl_type=params.crawl_type,
                http_user=http_user,  # Pass auth credentials as strings
                http_pass=http_pass,
                # Pass tenant settings for tenant-aware Scrapy configuration
                tenant_crawler_settings=tenant.crawler_settings if tenant else None,
            ) as crawl:
                timings["crawl_and_parse"] = time.time() - start

                # Measure page processing time
                process_start = time.time()
                # Get job repo for heartbeat updates
                job_repo = container.job_repo()
                # Get per-tenant heartbeat interval (falls back to env default)
                current_tenant = container.tenant()
                heartbeat_interval_seconds = get_crawler_setting(
                    "crawl_heartbeat_interval_seconds",
                    current_tenant.crawler_settings if current_tenant else None,
                    default=settings.crawl_heartbeat_interval_seconds,
                )
                last_heartbeat_time = time.time()

                # Import for suicide check
                from intric.main.models import Status as JobStatus

                # Process pages with retry logic
                for page in crawl.pages:
                    num_pages += 1

                    # TIME-BASED HEARTBEAT: Update every N seconds (not every N pages)
                    # This handles slow-loading pages correctly - a 3min/page site won't be preempted
                    current_time = time.time()
                    if current_time - last_heartbeat_time >= heartbeat_interval_seconds:
                        try:
                            await job_repo.touch_job(job_id)
                            last_heartbeat_time = current_time
                            logger.debug(
                                f"Heartbeat: crawl job still alive after {num_pages} pages",
                                extra={"job_id": str(job_id), "pages_processed": num_pages},
                            )

                            # IN-LOOP SUICIDE CHECK: Detect preemption immediately
                            # If user triggered recrawl and this job was marked FAILED,
                            # stop NOW to avoid zombie writer corrupting new crawl's data
                            current_job = await job_repo.get_job(job_id)
                            if current_job and current_job.status == JobStatus.FAILED:
                                logger.warning(
                                    "Worker detected preemption during heartbeat - stopping immediately",
                                    extra={
                                        "job_id": str(job_id),
                                        "website_id": str(params.website_id),
                                        "pages_processed": num_pages,
                                    },
                                )
                                return {"status": "preempted_during_crawl", "pages_crawled": num_pages}

                        except Exception as heartbeat_exc:
                            # Non-fatal: Log warning but continue crawling
                            logger.warning(
                                f"Failed to update heartbeat: {heartbeat_exc}",
                                extra={"job_id": str(job_id)},
                            )

                    # Process page with retry logic
                    success, error_message = await process_page_with_retry(
                        page=page,
                        uploader=uploader,
                        session=session,
                        params=params,
                        website=website,
                        tenant_slug=tenant.slug if tenant else None,
                    )

                    if success:
                        crawled_titles.add(page.url)
                    else:
                        num_failed_pages += 1
                        logger.error(
                            f"Failed page: {page.url} - {error_message}",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(website.tenant_id),
                                "tenant_slug": tenant.slug if tenant else None,
                                "page_url": page.url,
                                "embedding_model": getattr(website.embedding_model, "name", None),
                            },
                        )
                timings["process_pages"] = time.time() - process_start

                # Measure file processing time
                file_start = time.time()
                # Process downloaded files with content hash checking
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

                        # File changed or new - process normally
                        # Create explicit savepoint for proper transaction handling
                        savepoint = await session.begin_nested()
                        try:
                            await uploader.process_file(
                                filepath=file,
                                filename=filename,
                                website_id=params.website_id,
                                embedding_model=website.embedding_model,
                                content_hash=new_file_hash,  # Store hash during creation
                            )
                            await savepoint.commit()
                            # ✅ PERFORMANCE FIX: Use set.add() instead of list.append()
                            crawled_titles.add(filename)
                        except Exception:
                            await savepoint.rollback()
                            raise
                    except Exception:
                        logger.exception(
                            "Exception while uploading file",
                            extra={
                                "website_id": str(params.website_id),
                                "tenant_id": str(website.tenant_id),
                                "tenant_slug": tenant.slug if tenant else None,
                                "filename": filename,
                                "embedding_model": getattr(website.embedding_model, "name", None),
                            },
                        )
                        num_failed_files += 1
                timings["process_files"] = time.time() - file_start

            # Measure cleanup phase (delete stale blobs)
            cleanup_start = time.time()
            # ✅ PERFORMANCE FIX: Batch delete instead of N individual queries
            # Collect stale titles (set difference is O(n))
            stale_titles = [
                title for title in existing_titles if title not in crawled_titles
            ]

            # Batch delete in ONE query instead of N individual queries
            if stale_titles:
                num_deleted_blobs = await info_blob_repo.batch_delete_by_titles_and_website(
                    titles=stale_titles, website_id=params.website_id
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

            # Measure website size update
            update_start = time.time()
            await update_website_size_service.update_website_size(website_id=website.id)
            timings["update_size"] = time.time() - update_start

            # Update last_crawled_at timestamp
            # Why: Track crawl completion time independently from record updates
            # Use database server time for timezone correctness
            from intric.database.tables.websites_table import Websites as WebsitesTable

            stmt = (
                sa.update(WebsitesTable)
                .where(WebsitesTable.id == params.website_id)
                .where(WebsitesTable.tenant_id == website.tenant_id)  # Tenant isolation
                .values(last_crawled_at=sa.func.now())
            )
            await session.execute(stmt)

            # Calculate file skip rate for performance analysis
            file_skip_rate = (num_skipped_files / num_files * 100) if num_files > 0 else 0

            # Structured crawl summary for easy log scanning
            summary = [
                "=" * 60,
                f"CRAWL FINISHED: {params.url}",
                "-" * 60,
                f"Pages:   {num_pages} crawled, {num_failed_pages} failed",
                f"Files:   {num_files} downloaded, {num_failed_files} failed, {num_skipped_files} skipped ({file_skip_rate:.1f}%)",
                f"Cleanup: {num_deleted_blobs} stale entries removed",
                "=" * 60,
            ]
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

            # SUICIDE CHECK: Verify job wasn't preempted while we were crawling
            # If another user triggered a recrawl and safe preemption marked this job FAILED,
            # we should NOT write results (a new crawl is already running)
            from intric.main.models import Status as JobStatus
            current_job = await job_repo.get_job(job_id)
            if current_job and current_job.status == JobStatus.FAILED:
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

            crawl_run = await crawl_run_repo.one(params.run_id)
            crawl_run.update(
                pages_crawled=num_pages,
                files_downloaded=num_files,
                pages_failed=num_failed_pages,
                files_failed=num_failed_files,
            )
            await crawl_run_repo.update(crawl_run)

            # ✅ CIRCUIT BREAKER: Update failure tracking and exponential backoff
            # Why: Prevent wasted resources on persistently failing websites
            from intric.database.tables.websites_table import Websites as WebsitesTable

            # Determine if crawl was successful
            # Success = at least one item (page or file) AND not everything failed
            total_items = num_pages + num_files
            total_failed = num_failed_pages + num_failed_files

            crawl_successful = total_items > 0 and total_failed < total_items

            if crawl_successful:
                # Success: Reset circuit breaker
                logger.info(
                    f"Crawl successful, resetting circuit breaker for website {params.website_id}"
                )
                stmt = (
                    sa.update(WebsitesTable)
                    .where(WebsitesTable.id == params.website_id)
                    .where(WebsitesTable.tenant_id == website.tenant_id)
                    .values(consecutive_failures=0, next_retry_at=None)
                )
                await session.execute(stmt)
            else:
                # Failure: Increment counter and apply exponential backoff
                # Get current failure count
                current_failures_stmt = sa.select(WebsitesTable.consecutive_failures).where(
                    WebsitesTable.id == params.website_id
                )
                current_failures = await session.scalar(current_failures_stmt) or 0
                new_failures = current_failures + 1

                # Auto-disable threshold: Stop trying after too many failures
                # Why: Prevents wasting resources on permanently dead sites
                MAX_FAILURES_BEFORE_DISABLE = 10

                if new_failures >= MAX_FAILURES_BEFORE_DISABLE:
                    # Auto-disable: Set update_interval to NEVER
                    from intric.websites.domain.website import UpdateInterval

                    logger.error(
                        f"Website {params.website_id} auto-disabled after {new_failures} consecutive failures. "
                        f"User action required to re-enable.",
                        extra={
                            "website_id": str(params.website_id),
                            "url": website.url,
                            "consecutive_failures": new_failures,
                        },
                    )

                    stmt = (
                        sa.update(WebsitesTable)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == website.tenant_id)
                        .values(
                            consecutive_failures=new_failures,
                            update_interval=UpdateInterval.NEVER,  # Auto-disable
                            next_retry_at=None,  # Clear retry time
                        )
                    )
                    await session.execute(stmt)
                else:
                    # Normal exponential backoff: 1h, 2h, 4h, 8h, 16h, 24h max
                    # Formula: 2^(n-1) gives: 1st=1h, 2nd=2h, 3rd=4h, 4th=8h, 5th=16h, 6th+=24h
                    backoff_hours = min(2 ** (new_failures - 1), 24)
                    next_retry = datetime.now(timezone.utc) + timedelta(hours=backoff_hours)

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

                    stmt = (
                        sa.update(WebsitesTable)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == website.tenant_id)
                        .values(consecutive_failures=new_failures, next_retry_at=next_retry)
                    )
                    await session.execute(stmt)

            # Audit logging for website crawl
            from intric.audit.domain.action_types import ActionType
            from intric.audit.domain.entity_types import EntityType

            audit_service = container.audit_service()

            # Determine actor (crawl is typically triggered by a user or system)
            # Use website owner or system actor
            actor_id = website.user_id if hasattr(website, 'user_id') and website.user_id else current_tenant.id

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
                        "name": getattr(website, 'name', website.url),
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

        return task_manager.successful()
    finally:
        if limiter is not None and tenant is not None and acquired:
            await limiter.release(tenant.id)
            await _reset_tenant_retry_delay(
                tenant_id=tenant.id, redis_client=redis_client
            )

        # P1 FIX: Cleanup Redis retry counters to prevent memory leak
        # Why: Counters persist after job completion, causing Redis bloat
        if redis_client and job_id:
            try:
                await redis_client.delete(
                    f"job:{job_id}:start_time", f"job:{job_id}:retry_count"
                )
            except Exception:
                pass  # Best effort cleanup
