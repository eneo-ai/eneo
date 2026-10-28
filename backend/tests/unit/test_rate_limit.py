"""Unit tests for the Redis rate limiter and its 429."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import redis.exceptions
from fastapi import HTTPException

from eneo.redis.rate_limit import (
    RATE_LIMIT_SCRIPT,
    RateLimitConfig,
    RateLimitExceededError,
    RateLimitResult,
    RateLimitServiceUnavailableError,
    check_rate_limit,
    enforce_rate_limit,
    raise_rate_limited,
)

CONFIG = RateLimitConfig(max_requests=5, window_seconds=60, key_prefix="test:limit")


def _redis(count: int, ttl: int = 60) -> AsyncMock:
    client = AsyncMock()
    client.eval = AsyncMock(return_value=[count, ttl])
    return client


def test_a_limit_without_its_own_bucket_cannot_be_built():
    """A forgotten prefix used to share the audit-session bucket."""
    with pytest.raises(TypeError):
        RateLimitConfig(max_requests=5, window_seconds=60)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("count", "allowed", "remaining"), [(1, True, 4), (5, True, 0), (6, False, 0)]
)
async def test_check_counts_against_the_limit(count, allowed, remaining):
    result = await check_rate_limit(_redis(count, ttl=42), "test:key", CONFIG)

    assert result.allowed is allowed
    assert result.current_count == count
    assert result.remaining == remaining
    assert result.retry_after_seconds == 42


async def test_check_passes_the_window_to_the_script():
    client = _redis(1)

    await check_rate_limit(client, "test:key", CONFIG)

    client.eval.assert_awaited_once_with(RATE_LIMIT_SCRIPT, 1, "test:key", 60)


async def test_redis_error_is_reported_as_unavailable():
    client = AsyncMock()
    client.eval = AsyncMock(side_effect=redis.exceptions.ConnectionError("refused"))

    with pytest.raises(RateLimitServiceUnavailableError) as caught:
        await check_rate_limit(client, "test:key", CONFIG)

    assert "refused" in str(caught.value.original_error)


async def test_enforce_uses_the_limits_own_key_and_raises_over_it():
    client = _redis(6, ttl=17)
    user_id, tenant_id = uuid4(), uuid4()

    with pytest.raises(RateLimitExceededError) as caught:
        await enforce_rate_limit(client, user_id, tenant_id, CONFIG)

    assert client.eval.await_args.args[2] == f"test:limit:{user_id}:{tenant_id}"
    assert caught.value.result.retry_after_seconds == 17
    assert "6/5" in str(caught.value)


def test_refusal_answers_with_the_time_left_in_the_window():
    result = RateLimitResult(
        allowed=False,
        current_count=2,
        max_requests=1,
        window_seconds=60,
        retry_after_seconds=40,
    )

    with pytest.raises(HTTPException) as caught:
        raise_rate_limited(result, "Slow down.")

    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "40"}
    assert caught.value.detail == {
        "code": "rate_limit_exceeded",
        "message": "Slow down.",
        "retry_after_seconds": 40,
    }
