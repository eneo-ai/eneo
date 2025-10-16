"""Unit tests for the per-tenant concurrency limiter."""

from uuid import uuid4

import pytest

from intric.worker.tenant_concurrency import TenantConcurrencyLimiter


class FakeRedis:
    """Minimal async Redis stub used to validate semaphore behaviour."""

    def __init__(self):
        self._store: dict[str, int] = {}
        self._ttl: dict[str, int] = {}

    async def eval(self, script: str, num_keys: int, key: str, *args):  # noqa: ARG002
        if "INCR" in script and "limit" in script:
            limit = int(args[0])
            ttl = int(args[1])
            if limit <= 0:
                return 1
            current = self._store.get(key, 0) + 1
            self._store[key] = current
            self._ttl[key] = ttl
            if current > limit:
                current -= 1
                if current <= 0:
                    self._store.pop(key, None)
                    self._ttl.pop(key, None)
                else:
                    self._store[key] = current
                return 0
            return current

        # release script
        ttl = int(args[0])
        current = self._store.get(key)
        if current is None:
            return 0
        current -= 1
        if current <= 0:
            self._store.pop(key, None)
            self._ttl.pop(key, None)
            return 0
        self._store[key] = current
        self._ttl[key] = ttl
        return current


@pytest.mark.asyncio
async def test_acquire_and_release_respects_limit():
    redis = FakeRedis()
    limiter = TenantConcurrencyLimiter(redis=redis, max_concurrent=2, ttl_seconds=60)
    tenant_id = uuid4()

    assert await limiter.acquire(tenant_id) is True
    assert await limiter.acquire(tenant_id) is True
    assert await limiter.acquire(tenant_id) is False  # limit reached

    # Release one slot and ensure we can acquire again
    await limiter.release(tenant_id)
    assert await limiter.acquire(tenant_id) is True


@pytest.mark.asyncio
async def test_limit_disabled_when_max_zero():
    redis = FakeRedis()
    limiter = TenantConcurrencyLimiter(redis=redis, max_concurrent=0, ttl_seconds=60)
    tenant_id = uuid4()

    # Limit disabled -> always acquires successfully, no redis writes
    for _ in range(5):
        assert await limiter.acquire(tenant_id) is True
    assert redis._store == {}
