"""Fixed-window rate limiting in Redis, and the one 429 a refusal becomes.

Each limit owns its bucket: `RateLimitConfig.key_prefix` is required, so a new
caller cannot silently share another limit's counter.
"""

import logging
from dataclasses import dataclass
from typing import Any, NoReturn, cast
from uuid import UUID

import redis.asyncio as aioredis
import redis.exceptions
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Atomic INCR, then the seconds left in the window, rounded up so a refusal
# never says "retry in 0 s" while its key still exists (TTL rounds to the
# nearest second). A key without a TTL (the first request of a window, or one
# whose EXPIRE was lost) gets the full window, so no key outlives it.
RATE_LIMIT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local pttl = redis.call('PTTL', KEYS[1])
if pttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    return {count, tonumber(ARGV[1])}
end
return {count, math.max(1, math.ceil(pttl / 1000))}
"""


@dataclass(frozen=True)
class RateLimitConfig:
    """One limit: at most `max_requests` per `window_seconds` per key."""

    max_requests: int
    window_seconds: int
    key_prefix: str


@dataclass(frozen=True)
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    current_count: int
    max_requests: int
    window_seconds: int
    # Seconds until the window resets, read in the same script as the count.
    retry_after_seconds: int

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


def build_rate_limit_key(user_id: UUID, tenant_id: UUID, prefix: str) -> str:
    """The per-user key of a limit: `{prefix}:{user_id}:{tenant_id}`."""
    return f"{prefix}:{user_id}:{tenant_id}"


async def check_rate_limit(
    redis_client: aioredis.Redis, key: str, config: RateLimitConfig
) -> RateLimitResult:
    """Count one request against `key` and report what is left of its window.

    Raises:
        RateLimitServiceUnavailableError: If Redis is unavailable. Each caller
            decides whether that fails open or closed.
    """
    try:
        # NOTE: This is Redis EVAL command for Lua scripts, NOT Python's eval()
        count, ttl = cast(
            list[int],
            await cast(Any, redis_client).eval(
                RATE_LIMIT_SCRIPT, 1, key, config.window_seconds
            ),
        )
    except redis.exceptions.RedisError as e:
        logger.error(f"Rate limit Redis error for key {key}: {e}", exc_info=True)
        raise RateLimitServiceUnavailableError(e) from e

    return RateLimitResult(
        allowed=count <= config.max_requests,
        current_count=count,
        max_requests=config.max_requests,
        window_seconds=config.window_seconds,
        retry_after_seconds=ttl,
    )


async def read_rate_limit_count(redis_client: aioredis.Redis, key: str) -> int:
    """Return the current window's count without consuming any of it.

    `check_rate_limit` increments, so a caller that only wants to report
    remaining capacity cannot use it: it would spend the budget it reports on.
    This returns the bare count rather than a `RateLimitResult`, because
    `allowed` on that type means "allowed after this request was counted" and
    would carry a second, quieter meaning here.

    Raises:
        RateLimitServiceUnavailableError: If Redis is unavailable or the stored
            counter is not an integer. Remaining capacity is never guessed.
    """
    try:
        raw = await cast(Any, redis_client).get(key)
    except redis.exceptions.RedisError as e:
        logger.error(f"Rate limit read error for key {key}: {e}", exc_info=True)
        raise RateLimitServiceUnavailableError(e) from e

    try:
        return 0 if raw is None else int(raw)
    except (TypeError, ValueError) as e:
        logger.error(f"Rate limit counter for key {key} is not an integer: {raw!r}")
        raise RateLimitServiceUnavailableError(e) from e


async def enforce_rate_limit(
    redis_client: aioredis.Redis,
    user_id: UUID,
    tenant_id: UUID,
    config: RateLimitConfig,
) -> RateLimitResult:
    """Count one request for a user and raise when it is over the limit.

    Raises:
        RateLimitExceededError: If rate limit is exceeded
        RateLimitServiceUnavailableError: If Redis is unavailable
    """
    key = build_rate_limit_key(user_id, tenant_id, config.key_prefix)
    result = await check_rate_limit(redis_client, key, config)

    if not result.allowed:
        raise RateLimitExceededError(result)

    return result


def raise_rate_limited(result: RateLimitResult, message: str) -> NoReturn:
    """The 429 every client reads: a flat `rate_limit_exceeded` body whose
    `retry_after_seconds` equals the `Retry-After` header, the time left in
    the window."""
    retry_after = result.retry_after_seconds
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "rate_limit_exceeded",
            "message": message,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
