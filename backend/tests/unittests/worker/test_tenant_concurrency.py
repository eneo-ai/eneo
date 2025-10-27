"""Unit tests for the per-tenant concurrency limiter."""

import asyncio
import time
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


# ============================================================================
# Circuit Breaker & Local Fallback Tests
# ============================================================================


@pytest.mark.asyncio
async def test_release_does_not_leak_when_circuit_open_after_redis_acquire(monkeypatch):
    """CRITICAL: Verify Redis-acquired slots are released even when circuit opens.

    This is a regression test for the release leak bug where:
    1. Task acquires via Redis (circuit closed)
    2. Circuit opens due to failure elsewhere
    3. Task calls release() → BUG: early return without Redis DECR
    4. Redis semaphore slot leaked until TTL expiry

    The fix ensures Redis release is always attempted for Redis-acquired slots,
    regardless of circuit breaker state.
    """
    redis = FakeRedis()
    tenant_id = uuid4()
    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=2,
        ttl_seconds=60,
        circuit_break_seconds=30,
    )

    # Acquire slot via Redis (circuit closed)
    assert await limiter.acquire(tenant_id) is True

    # Verify Redis has the slot
    key = limiter._key(tenant_id)
    assert redis._store.get(key) == 1, "Redis should have 1 active slot"

    # Force circuit to open (simulate Redis failure elsewhere)
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    await limiter._open_circuit(now)

    # Verify circuit is open
    assert limiter._is_circuit_open(now) is True

    # Attempt release - this should NOT leak the slot
    await limiter.release(tenant_id)

    # CRITICAL: Verify Redis slot was released (no leak)
    # The bug would leave redis._store[key] == 1
    final_count = redis._store.get(key)
    assert final_count is None or final_count == 0, (
        f"Release should decrement Redis counter even when circuit open. "
        f"Got count={final_count}, expected 0 or None (no leak)"
    )


@pytest.mark.asyncio
async def test_circuit_opens_on_exception_and_stays_open_for_duration(monkeypatch):
    """Verify circuit breaker opens on Redis failure and stays open for configured duration."""
    redis = FakeRedis()
    tenant_id = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=2,
        ttl_seconds=60,
        circuit_break_seconds=5,  # 5 second circuit
    )

    # Simulate Redis failure
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis connection failed")

    limiter.redis = FailingRedis()  # type: ignore

    # First acquire attempt should open circuit
    t0 = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: t0)

    # Acquire fails to Redis but succeeds via fallback
    result = await limiter.acquire(tenant_id)
    assert result is True  # Succeeds via fallback

    # Circuit should be open now
    assert limiter._is_circuit_open(t0) is True

    # Advance time within circuit window → still open
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 4.9)
    assert limiter._is_circuit_open(t0 + 4.9) is True

    # Advance time beyond circuit window → closed
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 5.1)
    assert limiter._is_circuit_open(t0 + 5.1) is False


@pytest.mark.asyncio
async def test_circuit_closes_on_redis_recovery(monkeypatch):
    """Verify circuit closes when Redis recovers and successful operation completes."""
    redis = FakeRedis()
    tenant_id = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=1,
        ttl_seconds=60,
        circuit_break_seconds=30,
    )

    # Manually open circuit (simulate previous failure)
    t0 = 100.0
    monkeypatch.setattr(time, "monotonic", lambda: t0)
    await limiter._open_circuit(t0)
    assert limiter._is_circuit_open(t0) is True

    # Move time forward beyond circuit window
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 31)

    # Next acquire with working Redis should close circuit
    assert await limiter.acquire(tenant_id) is True

    # Circuit should now be closed
    assert limiter._is_circuit_open(t0 + 31) is False

    # Cleanup
    await limiter.release(tenant_id)


@pytest.mark.asyncio
async def test_local_fallback_enforces_limit_with_lock():
    """Verify local fallback enforces limit correctly under concurrent load."""
    redis = FakeRedis()
    tenant_id = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=3,
        ttl_seconds=60,
        circuit_break_seconds=5,
        local_limit=3,  # Explicit local limit
    )

    # Force circuit open
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis unavailable")

    limiter.redis = FailingRedis()  # type: ignore

    # First call opens circuit and uses fallback
    result1 = await limiter.acquire(tenant_id)
    assert result1 is True  # First acquisition succeeds

    # Concurrent acquire attempts (all via fallback now)
    results = await asyncio.gather(*[limiter.acquire(tenant_id) for _ in range(10)])

    # Should allow 2 more (total 3 including first) via fallback
    # Total attempts: 1 (result1) + 10 (gather) = 11
    # With limit=3: 3 succeed, 8 fail
    succeeded = [result1] + [r for r in results if r]
    failed = [r for r in results if not r]

    assert len(succeeded) == 3, f"Expected 3 acquisitions, got {len(succeeded)}"
    assert len(failed) == 8, f"Expected 8 rejections (11 total - 3 limit), got {len(failed)}"

    # Cleanup
    for _ in range(len(succeeded)):
        await limiter.release(tenant_id)


@pytest.mark.asyncio
async def test_cleanup_expired_removes_old_entries(monkeypatch):
    """Verify _cleanup_expired() removes entries with past expiration times."""
    redis = FakeRedis()
    tenant_id1 = uuid4()
    tenant_id2 = uuid4()
    tenant_id3 = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=2,
        ttl_seconds=60,
        local_ttl_seconds=10,  # 10 second TTL for testing
    )

    # Force circuit open to use fallback
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis unavailable")

    limiter.redis = FailingRedis()  # type: ignore

    # Start time
    t0 = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: t0)

    # Acquire for 3 tenants at t0
    assert await limiter.acquire(tenant_id1) is True
    assert await limiter.acquire(tenant_id2) is True
    assert await limiter.acquire(tenant_id3) is True

    # Verify all 3 in local counts
    assert len(limiter._local_counts) == 3

    # Advance time beyond TTL (10 seconds)
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 11)

    # Trigger cleanup by attempting another acquire
    await limiter.acquire(tenant_id1)  # This triggers _cleanup_expired()

    # All old entries should be removed (expired)
    # Only the new acquire should be present
    assert len(limiter._local_counts) == 1, "Expired entries should be removed"


@pytest.mark.asyncio
async def test_task_fallback_flag_set_and_consumed():
    """Verify task fallback flag is properly set on acquire and consumed on release."""
    redis = FakeRedis()
    tenant_id = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=2,
        ttl_seconds=60,
        circuit_break_seconds=5,
    )

    # Force circuit open to trigger fallback
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis unavailable")

    limiter.redis = FailingRedis()  # type: ignore

    # Acquire via fallback → should set flag on current task
    result = await limiter.acquire(tenant_id)
    assert result is True

    # Verify flag was set
    task = asyncio.current_task()
    fallback_map = getattr(task, "_tenant_limiter_fallback", None)
    assert fallback_map is not None, "Fallback map should be set on task"
    assert fallback_map.get(tenant_id) is True, "Flag should be True for this tenant"

    # Release → should consume flag
    await limiter.release(tenant_id)

    # Verify flag was consumed (removed)
    fallback_map_after = getattr(task, "_tenant_limiter_fallback", None)
    assert fallback_map_after is None or tenant_id not in fallback_map_after, (
        "Flag should be consumed after release"
    )

    # Second release should be safe (no error, no-op)
    await limiter.release(tenant_id)  # Should not raise


@pytest.mark.asyncio
async def test_concurrent_fallback_calls_respect_per_tenant_limit():
    """Verify multiple tenants have independent fallback limits during circuit-open."""
    redis = FakeRedis()
    tenant_a = uuid4()
    tenant_b = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=2,
        ttl_seconds=60,
        circuit_break_seconds=5,
        local_limit=2,
    )

    # Force circuit open
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis unavailable")

    limiter.redis = FailingRedis()  # type: ignore

    # Trigger circuit open
    await limiter.acquire(tenant_a)

    # Each tenant should independently get 2 slots via fallback
    results_a = await asyncio.gather(*[limiter.acquire(tenant_a) for _ in range(5)])
    results_b = await asyncio.gather(*[limiter.acquire(tenant_b) for _ in range(5)])

    # Tenant A: 1 already acquired + 1 more from gather = 2 total (reached limit)
    # From the 5 gather calls: 1 succeeds, 4 fail
    assert results_a.count(True) == 1, "Tenant A should get 1 more slot (already has 1)"
    assert results_a.count(False) == 4

    # Tenant B: 2 succeed, 3 fail (independent limit)
    assert results_b.count(True) == 2, "Tenant B should get 2 slots independently"
    assert results_b.count(False) == 3

    # Verify no cross-tenant interference
    assert len(limiter._local_counts) == 2, "Should have 2 separate tenant entries"


@pytest.mark.asyncio
async def test_asyncio_current_task_none_safety(monkeypatch):
    """Verify flag marking/consuming is safe when asyncio.current_task() returns None."""

    # Monkeypatch current_task to return None
    monkeypatch.setattr(asyncio, "current_task", lambda: None)

    redis = FakeRedis()
    tenant_id = uuid4()

    limiter = TenantConcurrencyLimiter(
        redis=redis,
        max_concurrent=2,
        ttl_seconds=60,
        circuit_break_seconds=5,
    )

    # Force circuit open to trigger fallback path
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis unavailable")

    limiter.redis = FailingRedis()  # type: ignore

    # Acquire should work even without current_task
    result = await limiter.acquire(tenant_id)
    assert result is True  # Fallback still works

    # Release should be safe (no exception)
    await limiter.release(tenant_id)  # Should not raise
