"""Rate limiting infrastructure for audit session creation.

This module provides atomic rate limiting using Redis Lua scripts.
Extracted from routes.py for improved testability and separation of concerns.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

import redis.exceptions

logger = logging.getLogger(__name__)

# Lua script for atomic INCR + EXPIRE to prevent zombie keys
# When count == 1 (first request), set TTL. Otherwise, just increment.
# This ensures the TTL is only set once and keys auto-expire.
RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    max_requests: int = 5
    window_seconds: int = 3600  # 1 hour
    key_prefix: str = "rate_limit:audit_session"


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    current_count: int
    max_requests: int
    window_seconds: int

    @property
    def remaining(self) -> int:
        """Number of requests remaining in the current window."""
        return max(0, self.max_requests - self.current_count)


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, result: RateLimitResult):
        self.result = result
        super().__init__(
            f"Rate limit exceeded. {result.current_count}/{result.max_requests} "
            f"requests in {result.window_seconds}s window."
        )


class RateLimitServiceUnavailableError(Exception):
    """Raised when the rate limiting service (Redis) is unavailable."""

    def __init__(self, original_error: Exception):
        self.original_error = original_error
        super().__init__(f"Rate limiting service unavailable: {original_error}")


def build_rate_limit_key(
    user_id: UUID,
    tenant_id: UUID,
    prefix: str = "rate_limit:audit_session",
) -> str:
    """Build a Redis key for rate limiting.

    Args:
        user_id: The user's UUID
        tenant_id: The tenant's UUID
        prefix: Key prefix (default: rate_limit:audit_session)

    Returns:
        Redis key string in format: {prefix}:{user_id}:{tenant_id}
    """
    return f"{prefix}:{user_id}:{tenant_id}"


async def check_rate_limit(
    redis_client,
    key: str,
    config: Optional[RateLimitConfig] = None,
) -> RateLimitResult:
    """Check and increment rate limit atomically.

    Uses a Lua script to ensure atomic INCR + EXPIRE operation.
    This prevents race conditions and zombie keys.

    Args:
        redis_client: Async Redis client instance
        key: The rate limit key to check/increment
        config: Rate limit configuration (uses defaults if None)

    Returns:
        RateLimitResult with current count and allowed status

    Raises:
        RateLimitServiceUnavailableError: If Redis is unavailable
    """
    if config is None:
        config = RateLimitConfig()

    try:
        # NOTE: This is Redis EVAL command for Lua scripts, NOT Python's eval()
        # Redis EVAL is the standard, safe way to run atomic Lua scripts
        count = await redis_client.eval(
            RATE_LIMIT_SCRIPT,
            1,  # number of keys
            key,  # KEYS[1]
            config.window_seconds,  # ARGV[1] - TTL in seconds
        )

        return RateLimitResult(
            allowed=count <= config.max_requests,
            current_count=count,
            max_requests=config.max_requests,
            window_seconds=config.window_seconds,
        )

    except redis.exceptions.RedisError as e:
        logger.error(f"Rate limit Redis error for key {key}: {e}", exc_info=True)
        raise RateLimitServiceUnavailableError(e) from e


async def enforce_rate_limit(
    redis_client,
    user_id: UUID,
    tenant_id: UUID,
    config: Optional[RateLimitConfig] = None,
) -> RateLimitResult:
    """Enforce rate limit for a user, raising an exception if exceeded.

    This is a convenience function that combines key building, checking,
    and enforcement in one call.

    Args:
        redis_client: Async Redis client instance
        user_id: The user's UUID
        tenant_id: The tenant's UUID
        config: Rate limit configuration (uses defaults if None)

    Returns:
        RateLimitResult if allowed

    Raises:
        RateLimitExceededError: If rate limit is exceeded
        RateLimitServiceUnavailableError: If Redis is unavailable
    """
    if config is None:
        config = RateLimitConfig()

    key = build_rate_limit_key(user_id, tenant_id, config.key_prefix)
    result = await check_rate_limit(redis_client, key, config)

    if not result.allowed:
        raise RateLimitExceededError(result)

    return result
