"""Failed password-login attempts per account, counted in Redis.

Counting is keyed on the submitted login name, whether or not an account with
that name exists, so neither the limit nor the remaining-attempts figure
reveals which names are registered.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, cast

import redis.asyncio as aioredis
import redis.exceptions

from eneo.audit.infrastructure.rate_limiting import (
    RateLimitConfig,
    RateLimitServiceUnavailableError,
    check_rate_limit,
)

LOGIN_ATTEMPT_LIMIT = RateLimitConfig(
    max_requests=5,
    window_seconds=10 * 60,
    key_prefix="rate_limit:login",
)


@dataclass(frozen=True)
class LoginAttempt:
    """One counted attempt and what is left of the window after it."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


def _key(login_name: str) -> str:
    # Hashed so the key has a fixed size and carries no e-mail address.
    normalized = login_name.strip().casefold().encode("utf-8")
    return f"{LOGIN_ATTEMPT_LIMIT.key_prefix}:{hashlib.sha256(normalized).hexdigest()}"


async def count_login_attempt(
    redis_client: aioredis.Redis, login_name: str
) -> LoginAttempt:
    """Count an attempt before the password is checked.

    Counting first keeps the limit exact under concurrent requests: an attempt
    that is not allowed never reaches password verification.
    """
    key = _key(login_name)
    result = await check_rate_limit(redis_client, key, LOGIN_ATTEMPT_LIMIT)
    try:
        ttl = cast(int, await cast(Any, redis_client).ttl(key))
    except redis.exceptions.RedisError as error:
        raise RateLimitServiceUnavailableError(error) from error
    return LoginAttempt(
        allowed=result.allowed,
        remaining=result.remaining,
        retry_after_seconds=ttl if ttl > 0 else LOGIN_ATTEMPT_LIMIT.window_seconds,
    )


async def clear_login_attempts(redis_client: aioredis.Redis, login_name: str) -> None:
    """Forget earlier failures after a successful login."""
    try:
        await cast(Any, redis_client).delete(_key(login_name))
    except redis.exceptions.RedisError as error:
        raise RateLimitServiceUnavailableError(error) from error
