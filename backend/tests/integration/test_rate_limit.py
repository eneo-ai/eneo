"""The rate-limit script against a real Redis: count and remaining window."""

from uuid import uuid4

import pytest
from fastapi import HTTPException

from eneo.redis.rate_limit import RateLimitConfig, check_rate_limit, raise_rate_limited


@pytest.fixture
def limit() -> RateLimitConfig:
    return RateLimitConfig(
        max_requests=1, window_seconds=60, key_prefix=f"rate_limit:test:{uuid4()}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_after_is_what_is_left_of_the_window(redis_client, limit):
    key = f"{limit.key_prefix}:caller"
    first = await check_rate_limit(redis_client, key, limit)
    assert first.allowed
    assert first.retry_after_seconds == 60

    await redis_client.expire(key, 40)  # 20 s of the window have passed
    second = await check_rate_limit(redis_client, key, limit)

    assert not second.allowed
    assert second.current_count == 2
    assert 39 <= second.retry_after_seconds <= 40
    with pytest.raises(HTTPException) as caught:
        raise_rate_limited(second, "Slow down.")
    assert caught.value.headers == {"Retry-After": str(second.retry_after_seconds)}
    assert caught.value.detail["retry_after_seconds"] == second.retry_after_seconds


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_key_without_a_ttl_gets_the_window_back(redis_client, limit):
    key = f"{limit.key_prefix}:zombie"
    await redis_client.set(key, 7)

    result = await check_rate_limit(redis_client, key, limit)

    assert result.current_count == 8
    assert result.retry_after_seconds == 60
    assert 0 < await redis_client.ttl(key) <= 60


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_last_moment_of_a_window_still_says_to_wait(redis_client, limit):
    key = f"{limit.key_prefix}:edge"
    await check_rate_limit(redis_client, key, limit)
    await redis_client.pexpire(key, 400)  # TTL would round this to 0 s

    result = await check_rate_limit(redis_client, key, limit)

    assert not result.allowed
    assert result.retry_after_seconds == 1
