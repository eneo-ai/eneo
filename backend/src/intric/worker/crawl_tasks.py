import asyncio
import hashlib
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import UUID

from arq import Retry
from dependency_injector import providers
import redis.asyncio as aioredis
import sqlalchemy as sa
from sqlalchemy.exc import PendingRollbackError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

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

# Lua script for atomic slot release (matches TenantConcurrencyLimiter._release_lua)
# Duplicated here to enable release even when limiter object is unavailable
# (e.g., when tenant injection fails but we still need to release a pre-acquired slot)
# NOTE: Keep in sync with TenantConcurrencyLimiter._release_lua in tenant_concurrency.py
_RELEASE_SLOT_LUA = (
    "local key = KEYS[1]\n"
    "local ttl = tonumber(ARGV[1])\n"
    "local current = redis.call('GET', key)\n"
    "if not current then return 0 end\n"
    "current = redis.call('DECR', key)\n"
    "if not current or current <= 0 then\n"
    "  redis.call('DEL', key)\n"
    "  return 0\n"
    "end\n"
    "redis.call('EXPIRE', key, ttl)\n"
    "return current\n"
)


def _is_invalid_transaction_error(error: Exception) -> bool:
    """Check if error indicates an invalid/broken transaction state.

    Uses both exception types AND string matching for robustness
    across SQLAlchemy versions.

    Args:
        error: The exception to check

    Returns:
        True if this indicates a corrupted transaction that requires session recovery
    """
    # Type-based detection (preferred)
    if isinstance(error, (PendingRollbackError, InvalidRequestError)):
        return True

    # String-based fallback for edge cases
    error_msg = str(error).lower()
    return (
        "invalid transaction" in error_msg
        or "can't reconnect" in error_msg
        or "pending rollback" in error_msg
    )


def _is_invalid_transaction_error_msg(message: str | None) -> bool:
    """Check if an error message string indicates invalid transaction state.

    This is needed because process_page_with_retry() catches all exceptions
    and returns (False, error_message) rather than raising. We need to detect
    transaction corruption from the returned error message string.

    Args:
        message: The error message string to check

    Returns:
        True if this indicates a corrupted transaction that requires session recovery
    """
    if not message:
        return False
    msg_lower = message.lower()
    return (
        "invalid transaction" in msg_lower
        or "can't reconnect" in msg_lower
        or "pending rollback" in msg_lower
        or "autobegin is disabled" in msg_lower  # Session lost transaction state
        or "another operation is in progress" in msg_lower  # asyncpg connection busy
    )


async def _recover_session(
    container: Container,
    old_session: AsyncSession,
    created_sessions: list[AsyncSession],
    logger_instance,
) -> tuple[AsyncSession, any]:
    """Recover from an invalid transaction by creating a new session.

    CRITICAL: Aggressively cleans up old session to prevent
    'InterfaceError: another operation is in progress' from leaking into the new session.

    This function handles SQLAlchemy transaction corruption by:
    1. Expunging all objects to prevent accidental stale access
    2. Rolling back and closing the corrupted session (with timeouts)
    3. Creating a fresh session from the session manager
    4. Tracking the new session for cleanup in the finally block
    5. Updating the container to use the new session

    Args:
        container: DI container to update
        old_session: The corrupted session to clean up
        created_sessions: List to track sessions for cleanup
        logger_instance: Logger instance for metrics/debugging

    Returns:
        Tuple of (new_session, new_uploader) for continued processing
    """
    from intric.database.database import sessionmanager

    # 1. Aggressive Cleanup with timeouts to prevent hanging on wedged connections
    try:
        if old_session:
            # Detach all objects first to prevent accidental access to stale data
            old_session.expunge_all()
            try:
                # Attempt rollback with timeout to free locks
                await asyncio.wait_for(old_session.rollback(), timeout=2.0)
            except Exception:
                pass  # Rollback may fail if connection is truly broken

            # Close session with timeout - may return poisoned connection to pool
            try:
                await asyncio.wait_for(old_session.close(), timeout=2.0)
            except Exception:
                pass  # Close may hang if socket is wedged
    except Exception as cleanup_exc:
        logger_instance.warning(
            f"Error cleaning up old session during recovery: {cleanup_exc}"
        )

    # 2. Create fresh session via explicit factory (no context manager)
    # This avoids orphaned async generator that causes GC-triggered session.close()
    new_session = sessionmanager.create_session()

    # 3. Explicitly start transaction - required since autobegin=False
    await new_session.begin()

    # Track for cleanup in finally block
    created_sessions.append(new_session)

    # 4. Update container to use new session
    container.session.override(providers.Object(new_session))

    # Get fresh uploader with new session
    new_uploader = container.text_processor()

    logger_instance.info(
        "Session recovered and initialized",
        extra={"metric_name": "crawl.session.recovered", "metric_value": 1}
    )

    return new_session, new_uploader


async def execute_with_recovery(
    container: Container,
    session_holder: dict,
    created_sessions: list[AsyncSession],
    operation_name: str,
    operation: Callable[..., Any],
) -> Any:
    """Execute a database operation with automatic session recovery.

    Wraps the 'try-except-recover-retry' pattern into a reusable function
    to prevent cascading failures and code duplication. This is critical
    for post-processing operations that may fail due to corrupted transactions.

    The operation callable should:
    - Be async (awaitable)
    - Fetch fresh services from container if needed (they may have stale sessions)
    - Not require any arguments (use closure to capture needed values)

    Args:
        container: DI container for session override and service creation
        session_holder: Dict with 'session' and 'uploader' keys to update on recovery
        created_sessions: List to track sessions for cleanup
        operation_name: Human-readable name for logging
        operation: Async callable to execute (no arguments)

    Returns:
        Result from the operation

    Raises:
        Exception: Re-raises non-transaction errors
    """
    try:
        return await operation()
    except Exception as exc:
        # Check for both invalid transaction AND autobegin errors
        if _is_invalid_transaction_error(exc) or _is_invalid_transaction_error_msg(str(exc)):
            logger.warning(
                f"Recovering session for {operation_name}...",
                extra={"error": str(exc), "operation": operation_name}
            )

            # Perform Recovery
            new_session, new_uploader = await _recover_session(
                container,
                session_holder["session"],
                created_sessions,
                logger,
            )

            # Update References
            session_holder["session"] = new_session
            session_holder["uploader"] = new_uploader

            # FIX: Ensure transaction is started on recovered session
            # Why: _recover_session() calls begin(), but if there's any issue
            # or if the retry operation commits/rolls back, subsequent operations
            # may find no active transaction. This defensive check prevents
            # "Autobegin is disabled" errors in cascading recovery scenarios.
            if not session_holder["session"].in_transaction():
                await session_holder["session"].begin()

            # Retry Operation - caller must ensure fresh services are fetched
            try:
                return await operation()
            except Exception as retry_exc:
                logger.warning(
                    f"Retry failed after session recovery for {operation_name}",
                    extra={"error": str(retry_exc), "operation": operation_name},
                )
                raise
        else:
            raise


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
            # FIX: Ensure transaction is active before begin_nested()
            if not session.in_transaction():
                await session.begin()
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
            # CRITICAL: If transaction is corrupted, return immediately for caller recovery
            # Don't waste remaining retries on a session that can't recover
            if _is_invalid_transaction_error(e):
                error_msg = f"Transaction corrupted on attempt {attempt + 1}: {str(e)}"
                logger.warning(
                    f"Invalid transaction detected, returning for session recovery: {page.url}",
                    extra={
                        "website_id": str(params.website_id),
                        "tenant_id": str(website.tenant_id),
                        "tenant_slug": tenant_slug,
                        "page_url": page.url,
                        "attempt": attempt + 1,
                    },
                )
                return False, error_msg  # Return immediately, let caller recover session

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
            # Delete flag immediately - we now own this slot
            await _early_redis.delete(preacquired_key)
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
                    await redis_client.delete(preacquired_key)
                    logger.debug(
                        "Pre-acquired slot detected on retry (early check failed)",
                        extra={"job_id": str(job_id), "tenant_id": str(preacquired_tenant_id)},
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
                            tenant.crawler_settings if hasattr(tenant, 'crawler_settings') else None,
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
                            tenant.crawler_settings if hasattr(tenant, 'crawler_settings') else None,
                            default=settings.tenant_worker_semaphore_ttl_seconds,
                        )
                        release_key = f"tenant:{preacquired_tenant_id}:active_jobs"
                        await redis_client.eval(
                            _RELEASE_SLOT_LUA,
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
        # CRITICAL: Atomic status check to prevent worker resurrection
        # Why: Safe Watchdog may have marked this job FAILED while it was in ARQ queue.
        # Without this check, we'd blindly set IN_PROGRESS, "resurrecting" a dead job.
        # This uses Compare-and-Swap: only transitions QUEUED → IN_PROGRESS
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

            # Get resources
            crawler = container.crawler()
            uploader = container.text_processor()
            crawl_run_repo = container.crawl_run_repo()

            # Get services
            info_blob_repo = container.info_blob_repo()
            website_service = container.website_crud_service()
            website = await website_service.get_website(params.website_id)
            session = container.session()

            # Initialize session holder for recovery support
            # This allows session recovery to update the reference mid-processing
            session_holder["session"] = session
            session_holder["uploader"] = uploader

            # Accessor function to get current active session (handles recovery transparently)
            # Why: After session recovery, container.session.override() doesn't reliably
            # propagate to Factory-created services. Using this accessor ensures all
            # post-processing DB operations use the same recovered session.
            def current_session() -> AsyncSession:
                """Get the current active session (handles recovery transparently)."""
                return session_holder["session"]

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

                # Get batch size for periodic commits (bounds data loss on failure)
                batch_size = get_crawler_setting(
                    "crawl_page_batch_size",
                    tenant.crawler_settings if tenant else None,
                    default=settings.crawl_page_batch_size,
                )
                pages_since_commit = 0

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

                            # Refresh semaphore TTL to prevent expiry during long crawls
                            # Why: Semaphore TTL may be close to max crawl time
                            # Without refresh, counter could expire before job completes
                            if redis_client and tenant:
                                try:
                                    semaphore_ttl = get_crawler_setting(
                                        "tenant_worker_semaphore_ttl_seconds",
                                        tenant.crawler_settings if hasattr(tenant, 'crawler_settings') else None,
                                        default=settings.tenant_worker_semaphore_ttl_seconds,
                                    )
                                    concurrency_key = f"tenant:{tenant.id}:active_jobs"
                                    await redis_client.expire(concurrency_key, semaphore_ttl)
                                except Exception:
                                    pass  # Non-fatal: counter still valid, just not refreshed

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
                            # Handle invalid transaction during heartbeat
                            if _is_invalid_transaction_error(heartbeat_exc):
                                logger.warning(
                                    "Heartbeat skipped due to invalid transaction - will recover on next page",
                                    extra={"job_id": str(job_id)}
                                )
                            else:
                                # Non-fatal: Log warning but continue crawling
                                logger.warning(
                                    f"Failed to update heartbeat: {heartbeat_exc}",
                                    extra={"job_id": str(job_id)},
                                )

                    # Process page with retry logic using session_holder (may be recovered)
                    try:
                        success, error_message = await process_page_with_retry(
                            page=page,
                            uploader=session_holder["uploader"],
                            session=session_holder["session"],
                            params=params,
                            website=website,
                            tenant_slug=tenant.slug if tenant else None,
                        )

                        if success:
                            crawled_titles.add(page.url)
                            pages_since_commit += 1

                            # Batched commit to bound data loss
                            if pages_since_commit >= batch_size:
                                try:
                                    await session_holder["session"].commit()
                                    await session_holder["session"].begin()
                                    pages_since_commit = 0
                                    logger.debug(
                                        f"Committed batch of {batch_size} pages",
                                        extra={
                                            "batch_size": batch_size,
                                            "total_pages": num_pages,
                                            "job_id": str(job_id),
                                        }
                                    )
                                except Exception as commit_exc:
                                    if _is_invalid_transaction_error(commit_exc):
                                        # Recover session and continue
                                        logger.warning(
                                            "Invalid transaction during batch commit, recovering...",
                                            extra={
                                                "job_id": str(job_id),
                                                "pages_since_commit": pages_since_commit,
                                            }
                                        )
                                        new_session, new_uploader = await _recover_session(
                                            container,
                                            session_holder["session"],
                                            created_sessions,
                                            logger,
                                        )
                                        session_holder["session"] = new_session
                                        session_holder["uploader"] = new_uploader
                                        pages_since_commit = 0
                                    else:
                                        raise
                        else:
                            # CRITICAL: Check if failure is due to invalid transaction
                            # process_page_with_retry catches exceptions and returns (False, msg)
                            # We must detect transaction corruption from the message string
                            if _is_invalid_transaction_error_msg(error_message):
                                logger.warning(
                                    "Invalid transaction detected from page failure, recovering...",
                                    extra={
                                        "job_id": str(job_id),
                                        "page_url": page.url,
                                        "error": error_message,
                                    }
                                )
                                # Recover session
                                new_session, new_uploader = await _recover_session(
                                    container,
                                    session_holder["session"],
                                    created_sessions,
                                    logger,
                                )
                                session_holder["session"] = new_session
                                session_holder["uploader"] = new_uploader
                                pages_since_commit = 0

                                # Retry this page with recovered session
                                try:
                                    retry_success, retry_error = await process_page_with_retry(
                                        page=page,
                                        uploader=session_holder["uploader"],
                                        session=session_holder["session"],
                                        params=params,
                                        website=website,
                                        tenant_slug=tenant.slug if tenant else None,
                                    )
                                    if retry_success:
                                        crawled_titles.add(page.url)
                                        pages_since_commit += 1
                                    else:
                                        num_failed_pages += 1
                                        logger.error(
                                            f"Page still failed after session recovery: {page.url}",
                                            extra={"error": retry_error}
                                        )
                                except Exception as recovery_retry_exc:
                                    num_failed_pages += 1
                                    logger.error(
                                        f"Page failed during recovery retry: {page.url}",
                                        extra={"error": str(recovery_retry_exc)}
                                    )
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

                    except Exception as page_exc:
                        # Check if this is a recoverable transaction error
                        if _is_invalid_transaction_error(page_exc):
                            logger.warning(
                                "Invalid transaction detected during page processing, recovering...",
                                extra={
                                    "job_id": str(job_id),
                                    "page_url": page.url,
                                    "pages_since_commit": pages_since_commit,
                                    "error": str(page_exc),
                                }
                            )

                            # Recover session
                            new_session, new_uploader = await _recover_session(
                                container,
                                session_holder["session"],
                                created_sessions,
                                logger,
                            )
                            session_holder["session"] = new_session
                            session_holder["uploader"] = new_uploader
                            pages_since_commit = 0

                            # Retry this page with recovered session
                            try:
                                success, error_message = await process_page_with_retry(
                                    page=page,
                                    uploader=session_holder["uploader"],
                                    session=session_holder["session"],
                                    params=params,
                                    website=website,
                                    tenant_slug=tenant.slug if tenant else None,
                                )
                                if success:
                                    crawled_titles.add(page.url)
                                    pages_since_commit += 1
                                else:
                                    num_failed_pages += 1
                            except Exception as retry_exc:
                                num_failed_pages += 1
                                logger.error(
                                    f"Page failed even after session recovery: {page.url}",
                                    extra={
                                        "job_id": str(job_id),
                                        "error": str(retry_exc),
                                    }
                                )
                        else:
                            # Non-transaction error, just count as failed
                            num_failed_pages += 1
                            logger.error(
                                f"Unexpected error processing page: {page.url} - {page_exc}",
                                extra={
                                    "website_id": str(params.website_id),
                                    "tenant_id": str(website.tenant_id),
                                    "page_url": page.url,
                                },
                            )

                # Final commit for any remaining uncommitted pages
                if pages_since_commit > 0:
                    try:
                        await session_holder["session"].commit()
                        await session_holder["session"].begin()
                        logger.debug(
                            f"Final commit of {pages_since_commit} remaining pages",
                            extra={"pages_since_commit": pages_since_commit, "job_id": str(job_id)}
                        )
                    except Exception:
                        pass  # Best effort - pages already processed

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
                        # Use session_holder for recovery support
                        # FIX: Session recovery if transaction context is closed
                        # Why: in_transaction()==False but begin() can still fail if the
                        # session's outer context manager is closed. Need fresh session.
                        sess = session_holder["session"]
                        try:
                            if not sess.in_transaction():
                                await sess.begin()
                            savepoint = await sess.begin_nested()
                        except Exception as tx_exc:
                            if _is_invalid_transaction_error(tx_exc):
                                # Session context manager is closed, need recovery
                                new_session, new_uploader = await _recover_session(
                                    container,
                                    sess,
                                    created_sessions,
                                    logger,
                                )
                                session_holder["session"] = new_session
                                session_holder["uploader"] = new_uploader
                                sess = new_session
                                if not sess.in_transaction():
                                    await sess.begin()
                                savepoint = await sess.begin_nested()
                            else:
                                raise
                        try:
                            await session_holder["uploader"].process_file(
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
                    except Exception as file_exc:
                        # Check if this is a recoverable transaction error
                        if _is_invalid_transaction_error(file_exc):
                            logger.warning(
                                "Invalid transaction during file processing, recovering...",
                                extra={
                                    "job_id": str(job_id),
                                    "crawled_filename": filename,
                                }
                            )
                            # Recover session
                            new_session, new_uploader = await _recover_session(
                                container,
                                session_holder["session"],
                                created_sessions,
                                logger,
                            )
                            session_holder["session"] = new_session
                            session_holder["uploader"] = new_uploader

                            # Retry this file with recovered session
                            # Session was just recovered, should be in clean state
                            try:
                                sess = session_holder["session"]
                                if not sess.in_transaction():
                                    await sess.begin()
                                savepoint = await sess.begin_nested()
                                await session_holder["uploader"].process_file(
                                    filepath=file,
                                    filename=filename,
                                    website_id=params.website_id,
                                    embedding_model=website.embedding_model,
                                    content_hash=new_file_hash,
                                )
                                await savepoint.commit()
                                crawled_titles.add(filename)
                            except Exception as retry_exc:
                                try:
                                    await savepoint.rollback()
                                except Exception:
                                    pass
                                num_failed_files += 1
                                logger.error(
                                    f"File failed even after session recovery: {filename}",
                                    extra={
                                        "job_id": str(job_id),
                                        "error": str(retry_exc),
                                    }
                                )
                        else:
                            logger.exception(
                                "Exception while uploading file",
                                extra={
                                    "website_id": str(params.website_id),
                                    "tenant_id": str(website.tenant_id),
                                    "tenant_slug": tenant.slug if tenant else None,
                                    "crawled_filename": filename,
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
            # Wrapped with recovery fallback in case session was corrupted during page processing
            if stale_titles:
                try:
                    num_deleted_blobs = await info_blob_repo.batch_delete_by_titles_and_website(
                        titles=stale_titles, website_id=params.website_id
                    )
                except Exception as delete_exc:
                    if _is_invalid_transaction_error(delete_exc):
                        logger.warning(
                            "Recovering session for stale blob cleanup...",
                            extra={"job_id": str(job_id), "num_stale": len(stale_titles)}
                        )
                        new_session, new_uploader = await _recover_session(
                            container, session_holder["session"], created_sessions, logger
                        )
                        session_holder["session"] = new_session
                        session_holder["uploader"] = new_uploader
                        # Retry with fresh repo from container
                        info_blob_repo = container.info_blob_repo()
                        num_deleted_blobs = await info_blob_repo.batch_delete_by_titles_and_website(
                            titles=stale_titles, website_id=params.website_id
                        )
                    else:
                        raise
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

            async def _do_update_size():
                # FIX: Use current_session() directly instead of container service
                # Why: Container.session.override() doesn't reliably propagate to
                # Factory-created services after session recovery. This caused
                # "Autobegin is disabled" errors when _do_update_size() and
                # _do_timestamp_update() used different sessions.
                sess = current_session()

                # Inline the SQL from UpdateWebsiteSizeService to use our session
                from intric.database.tables.info_blobs_table import InfoBlobs as InfoBlobsTable

                update_size_stmt = (
                    sa.select(sa.func.coalesce(sa.func.sum(InfoBlobsTable.size), 0))
                    .where(InfoBlobsTable.website_id == website.id)
                    .scalar_subquery()
                )
                stmt = (
                    sa.update(WebsitesTable)
                    .where(WebsitesTable.id == website.id)
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
            from intric.database.tables.websites_table import Websites as WebsitesTable

            last_crawled_stmt = (
                sa.update(WebsitesTable)
                .where(WebsitesTable.id == params.website_id)
                .where(WebsitesTable.tenant_id == website.tenant_id)  # Tenant isolation
                .values(last_crawled_at=sa.func.now())
            )

            async def _do_timestamp_update():
                # FIX: Use current_session() for consistency with _do_update_size()
                sess = current_session()
                # Defensive: Ensure transaction is active after potential recovery
                # Why: After session recovery, transaction may not be started if
                # execute_with_recovery doesn't guarantee it
                if not sess.in_transaction():
                    await sess.begin()
                await sess.execute(last_crawled_stmt)
                # No commit here - let final _do_complete_job() commit everything atomically.
                # Committing mid-flow closes the context manager's transaction, causing
                # "Can't operate on closed transaction" errors in subsequent operations.

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="last_crawled_at_update",
                operation=_do_timestamp_update,
            )

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
            # FIX: Use current_session() directly instead of container.job_repo()
            # (container services have stale sessions after recovery)
            from intric.main.models import Status as JobStatus
            from intric.database.tables.job_table import Jobs

            async def _do_suicide_check():
                sess = current_session()
                if not sess.in_transaction():
                    await sess.begin()
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
            # FIX: Use current_session() directly instead of container.crawl_run_repo()
            # (container services have stale sessions after recovery)
            from intric.database.tables.websites_table import CrawlRuns

            async def _do_crawl_run_update():
                sess = current_session()
                if not sess.in_transaction():
                    await sess.begin()
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

            # ✅ CIRCUIT BREAKER: Update failure tracking and exponential backoff
            # Why: Prevent wasted resources on persistently failing websites
            # Note: WebsitesTable import already done above for last_crawled_at

            # Determine if crawl was successful
            # Success = at least one item (page or file) AND not everything failed
            total_items = num_pages + num_files
            total_failed = num_failed_pages + num_failed_files
            crawl_successful = total_items > 0 and total_failed < total_items

            async def _do_circuit_breaker_update():
                """Update circuit breaker state with appropriate backoff/reset."""
                # FIX: Use current_session() for consistency with other operations
                sess = current_session()
                if crawl_successful:
                    # Success: Reset circuit breaker
                    logger.info(
                        f"Crawl successful, resetting circuit breaker for website {params.website_id}"
                    )
                    reset_stmt = (
                        sa.update(WebsitesTable)
                        .where(WebsitesTable.id == params.website_id)
                        .where(WebsitesTable.tenant_id == website.tenant_id)
                        .values(consecutive_failures=0, next_retry_at=None)
                    )
                    await sess.execute(reset_stmt)
                else:
                    # Failure: Increment counter and apply exponential backoff
                    # Get current failure count
                    current_failures_stmt = sa.select(WebsitesTable.consecutive_failures).where(
                        WebsitesTable.id == params.website_id
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
                                "url": website.url,
                                "consecutive_failures": new_failures,
                            },
                        )

                        disable_stmt = (
                            sa.update(WebsitesTable)
                            .where(WebsitesTable.id == params.website_id)
                            .where(WebsitesTable.tenant_id == website.tenant_id)
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

                        backoff_stmt = (
                            sa.update(WebsitesTable)
                            .where(WebsitesTable.id == params.website_id)
                            .where(WebsitesTable.tenant_id == website.tenant_id)
                            .values(consecutive_failures=new_failures, next_retry_at=next_retry)
                        )
                        await sess.execute(backoff_stmt)

            await execute_with_recovery(
                container=container,
                session_holder=session_holder,
                created_sessions=created_sessions,
                operation_name="circuit_breaker_update",
                operation=_do_circuit_breaker_update,
            )

            task_manager.result_location = (
                f"/api/v1/websites/{params.website_id}/info-blobs/"
            )

            # FIX: Handle job completion here using current_session() to avoid
            # stale session in task_manager. The task_manager was created with the
            # ORIGINAL session, so after session recovery, task_manager.job_service
            # has a stale session that will fail with "closed transaction" error.
            async def _do_complete_job():
                """Complete the job using current_session() directly."""
                from intric.database.tables.job_table import Jobs
                from intric.main.models import Status

                sess = current_session()
                if not sess.in_transaction():
                    await sess.begin()

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
                await sess.commit()

                logger.debug(
                    "Job completed via current_session()",
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
            await _reset_tenant_retry_delay(
                tenant_id=tenant.id, redis_client=redis_client
            )
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
                    "reason": "tenant_injection_failed" if tenant is None else "acquired_not_set",
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
                    await _fallback_redis.eval(
                        _RELEASE_SLOT_LUA,
                        1,
                        release_key,
                        str(settings.tenant_worker_semaphore_ttl_seconds),
                    )
            except Exception as release_exc:
                logger.error(
                    "Failed to release pre-acquired slot in fallback",
                    extra={
                        "job_id": str(job_id),
                        "tenant_id": str(preacquired_tenant_id),
                        "error": str(release_exc),
                    },
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

        # Clean up any recovery sessions we created
        # Why: Session recovery creates new sessions that must be closed
        # to prevent connection pool exhaustion
        for recovery_session in created_sessions:
            try:
                await recovery_session.close()
            except Exception:
                pass  # Best effort cleanup
