from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
import redis.exceptions

from intric.authentication.api_key_rate_limiter import ApiKeyRateLimiter
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import ApiKeyScopeType
from intric.main.config import get_settings, set_settings


class FakeRedis:
    def __init__(self, count: int, raise_error: bool = False):
        self.count = count
        self.raise_error = raise_error
        self.calls: list[tuple] = []

    async def eval(self, script, numkeys, key, ttl):
        self.calls.append((script, numkeys, key, ttl))
        if self.raise_error:
            raise redis.exceptions.RedisError("boom")
        return self.count


@pytest.mark.asyncio
async def test_rate_limit_allows_default_scope_limit():
    redis_client = FakeRedis(count=1)
    limiter = ApiKeyRateLimiter(redis_client=redis_client)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.TENANT.value,
        rate_limit=None,
    )

    await limiter.enforce(key)

    assert len(redis_client.calls) == 1


@pytest.mark.asyncio
async def test_rate_limit_exceeded_raises_error():
    redis_client = FakeRedis(count=2)
    limiter = ApiKeyRateLimiter(redis_client=redis_client)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.ASSISTANT.value,
        rate_limit=1,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await limiter.enforce(key)

    assert exc.value.status_code == 429
    assert exc.value.code == "rate_limit_exceeded"


@pytest.mark.asyncio
async def test_rate_limit_unlimited_skips_redis():
    redis_client = FakeRedis(count=1)
    limiter = ApiKeyRateLimiter(redis_client=redis_client)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.SPACE.value,
        rate_limit=-1,
    )

    await limiter.enforce(key)

    assert redis_client.calls == []


@pytest.mark.asyncio
async def test_rate_limit_fail_open_when_redis_unavailable():
    settings = get_settings()
    patched = settings.model_copy(update={"api_key_rate_limit_fail_open": True})
    set_settings(patched)

    redis_client = FakeRedis(count=1, raise_error=True)
    limiter = ApiKeyRateLimiter(redis_client=redis_client)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.SPACE.value,
        rate_limit=1,
    )

    try:
        await limiter.enforce(key)
    finally:
        set_settings(settings)


@pytest.mark.asyncio
async def test_rate_limit_fail_closed_when_redis_unavailable():
    """Redis unavailable + fail_open=False → 503."""
    settings = get_settings()
    patched = settings.model_copy(update={"api_key_rate_limit_fail_open": False})
    set_settings(patched)

    redis_client = FakeRedis(count=1, raise_error=True)
    limiter = ApiKeyRateLimiter(redis_client=redis_client)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.SPACE.value,
        rate_limit=1,
    )

    try:
        with pytest.raises(ApiKeyValidationError) as exc:
            await limiter.enforce(key)
        assert exc.value.status_code == 503
        assert exc.value.code == "rate_limit_unavailable"
    finally:
        set_settings(settings)


@pytest.mark.asyncio
async def test_rate_limit_fail_closed_when_redis_is_none():
    """Redis client is None + fail_open=False → 503."""
    settings = get_settings()
    patched = settings.model_copy(update={"api_key_rate_limit_fail_open": False})
    set_settings(patched)

    limiter = ApiKeyRateLimiter(redis_client=None)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.TENANT.value,
        rate_limit=100,
    )

    try:
        with pytest.raises(ApiKeyValidationError) as exc:
            await limiter.enforce(key)
        assert exc.value.status_code == 503
        assert exc.value.code == "rate_limit_unavailable"
    finally:
        set_settings(settings)


@pytest.mark.asyncio
async def test_rate_limit_exceeded_includes_headers():
    """Rate limit exceeded response includes Retry-After and X-RateLimit headers."""
    redis_client = FakeRedis(count=2)
    limiter = ApiKeyRateLimiter(redis_client=redis_client)

    key = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        scope_type=ApiKeyScopeType.ASSISTANT.value,
        rate_limit=1,
    )

    with pytest.raises(ApiKeyValidationError) as exc:
        await limiter.enforce(key)

    assert exc.value.headers is not None
    assert "Retry-After" in exc.value.headers
    assert "X-RateLimit-Limit" in exc.value.headers
    assert exc.value.headers["X-RateLimit-Remaining"] == "0"
    assert exc.value.headers["X-RateLimit-Limit"] == "1"
