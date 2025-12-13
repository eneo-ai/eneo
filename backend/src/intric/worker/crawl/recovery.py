"""Session recovery and retry utilities for crawler workers.

This module provides:
1. SQLAlchemy session recovery from transaction corruption
2. Exponential backoff calculation with full jitter
3. Redis-based job retry statistics tracking

The session recovery pattern handles SQLAlchemy transaction corruption by:
- Detecting invalid transaction state via exception type and message
- Aggressively cleaning up corrupted sessions with timeouts
- Creating fresh sessions from the session manager
- Updating DI container overrides

Usage:
    from intric.worker.crawl.recovery import (
        execute_with_recovery,
        calculate_exponential_backoff,
        update_job_retry_stats,
    )
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Any, Callable, TypedDict
from uuid import UUID

from dependency_injector import providers
from sqlalchemy.exc import InvalidRequestError, PendingRollbackError

if TYPE_CHECKING:
    import redis.asyncio as aioredis
    from sqlalchemy.ext.asyncio import AsyncSession

    from intric.main.container.container import Container

logger = logging.getLogger(__name__)

__all__ = [
    # Type definitions
    "SessionHolder",
    # Public API
    "execute_with_recovery",
    "calculate_exponential_backoff",
    "update_job_retry_stats",
    "reset_tenant_retry_delay",
    # Semi-public helpers (used directly in crawl_tasks.py for inline recovery)
    "is_invalid_transaction_error",
    "is_invalid_transaction_error_msg",
    "recover_session",
]


# ═══════════════════════════════════════════════════════════════════════════════
# TYPE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════


class SessionHolder(TypedDict):
    """Mutable container for session reference across recovery.

    Used to pass session by reference so recovery can update the caller's
    reference without changing function signatures.

    Attributes:
        session: The current SQLAlchemy async session
        uploader: The text processor service (depends on session)
    """

    session: Any  # AsyncSession - using Any to avoid import issues
    uploader: Any  # TextProcessor


# ═══════════════════════════════════════════════════════════════════════════════
# TRANSACTION ERROR DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


def is_invalid_transaction_error(error: Exception) -> bool:
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


def is_invalid_transaction_error_msg(message: str | None) -> bool:
    """Check if an error message string indicates invalid transaction state.

    Used to detect transaction corruption from error message strings when the
    original exception is not available (e.g., from logged/serialized errors).

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


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION RECOVERY
# ═══════════════════════════════════════════════════════════════════════════════


async def recover_session(
    container: "Container",
    old_session: "AsyncSession",
    created_sessions: list["AsyncSession"],
    logger_instance: logging.Logger,
) -> tuple["AsyncSession", Any]:
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
    # Import here to avoid circular imports - this pattern is intentional
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
        extra={"metric_name": "crawl.session.recovered", "metric_value": 1},
    )

    return new_session, new_uploader


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API: Session Recovery Wrapper (Session-per-Operation Pattern)
# ═══════════════════════════════════════════════════════════════════════════════


async def execute_with_recovery(
    container: "Container",
    session_holder: SessionHolder,
    created_sessions: list["AsyncSession"],
    operation_name: str,
    operation: Callable[..., Any],
) -> Any:
    """Execute a database operation with its own short-lived session.

    NEW ARCHITECTURE (Session-per-Operation Pattern):
    Each call creates a fresh session, executes the operation, commits, and
    returns the session to the pool. This prevents DB pool exhaustion for
    long-running tasks like crawls (5-30 minutes).

    The operation callable should:
    - Be async (awaitable)
    - Accept a single `session` parameter
    - Use the provided session for all DB operations
    - Return any result needed by the caller

    Args:
        container: DI container (used for recovery, not session creation)
        session_holder: Dict updated with current session for legacy compatibility
        created_sessions: List to track sessions for cleanup on error
        operation_name: Human-readable name for logging
        operation: Async callable that accepts (session) parameter

    Returns:
        Result from the operation

    Raises:
        Exception: Re-raises non-recoverable errors after cleanup

    Example:
        async def _do_update(session):
            stmt = sa.update(Table).where(...).values(...)
            await session.execute(stmt)
            # No commit needed - execute_with_recovery handles it

        result = await execute_with_recovery(
            container, session_holder, created_sessions,
            "website_update", _do_update
        )
    """
    from intric.database.database import sessionmanager

    session = None
    try:
        # Create fresh session for this operation
        session = sessionmanager.create_session()
        await session.begin()

        # Update session_holder for legacy code paths that read from it
        session_holder["session"] = session

        # Execute operation with the session
        result = await operation(session)

        # Commit on success
        await session.commit()

        logger.debug(
            f"Operation completed: {operation_name}",
            extra={"operation": operation_name, "status": "success"},
        )

        return result

    except Exception as exc:
        # Handle transaction errors with retry
        if is_invalid_transaction_error(exc) or is_invalid_transaction_error_msg(
            str(exc)
        ):
            logger.warning(
                f"Transaction error in {operation_name}, recovering...",
                extra={"error": str(exc), "operation": operation_name},
            )

            # Cleanup failed session
            if session is not None:
                try:
                    await asyncio.wait_for(session.rollback(), timeout=2.0)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(session.close(), timeout=2.0)
                except Exception:
                    pass

            # Retry with fresh session (session-per-operation: create, use, close)
            retry_session = None
            try:
                retry_session = sessionmanager.create_session()
                await retry_session.begin()
                # NOTE: Don't add to created_sessions - we close immediately below
                session_holder["session"] = retry_session

                result = await operation(retry_session)
                await retry_session.commit()

                logger.info(
                    f"Operation recovered: {operation_name}",
                    extra={
                        "operation": operation_name,
                        "metric_name": "crawl.operation.recovered",
                        "metric_value": 1,
                    },
                )
                return result

            except Exception as retry_exc:
                logger.warning(
                    f"Retry failed for {operation_name}",
                    extra={"error": str(retry_exc), "operation": operation_name},
                )
                if retry_session is not None:
                    try:
                        await retry_session.rollback()
                    except Exception:
                        pass
                raise

            finally:
                # Session-per-operation: Always close retry session when done
                if retry_session is not None:
                    try:
                        await retry_session.close()
                    except Exception:
                        pass
        else:
            # Non-transaction error - rollback and re-raise
            if session is not None:
                try:
                    await session.rollback()
                except Exception:
                    pass
            raise

    finally:
        # Always close the primary session (retry session has its own finally block)
        if session is not None and session not in created_sessions:
            try:
                await session.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API: Exponential Backoff
# ═══════════════════════════════════════════════════════════════════════════════


def calculate_exponential_backoff(
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


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API: Redis Retry Statistics
# ═══════════════════════════════════════════════════════════════════════════════


async def reset_tenant_retry_delay(
    *, tenant_id: UUID, redis_client: "aioredis.Redis | None"
) -> None:
    """Reset tenant retry delay counter in Redis.

    Best-effort cleanup - swallows exceptions to avoid disrupting main flow.

    Args:
        tenant_id: Tenant identifier
        redis_client: Redis connection (may be None)
    """
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


async def update_job_retry_stats(
    *,
    job_id: UUID,
    redis_client: "aioredis.Redis | None",
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
        - is_actual_failure=False -> retry_count stays 0, only max_age enforced

        Job tries to crawl but gets network timeout:
        - is_actual_failure=True -> retry_count increments, both limits enforced
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
