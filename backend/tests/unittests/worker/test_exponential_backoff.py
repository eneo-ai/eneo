"""Unit tests for exponential backoff in worker retry logic."""

import random
from uuid import uuid4

import pytest

from intric.worker.crawl_tasks import _tenant_retry_delay, _reset_tenant_retry_delay


class FakeBackoffRedis:
    """Minimal Redis stub for testing backoff counter logic."""

    def __init__(self):
        self.store: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.fail_expire_once = False

    async def incr(self, key: str) -> int:
        """Increment counter and return new value."""
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> None:
        """Set TTL on key."""
        if self.fail_expire_once:
            self.fail_expire_once = False
            raise Exception("Expire operation failed")
        self.ttls[key] = ttl

    async def delete(self, key: str) -> None:
        """Delete key."""
        self.store.pop(key, None)
        self.ttls.pop(key, None)


@pytest.mark.asyncio
async def test_backoff_increments_linearly():
    """Verify backoff delay increases linearly with failure count."""
    redis = FakeBackoffRedis()
    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 300.0
    ttl = 300

    # First failure: base_delay (30s)
    delay1 = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    # With jitter, should be approximately base_delay ± 25%
    assert 22.5 <= delay1 <= 37.5, f"First delay should be ~30s ± 25%, got {delay1}"

    # Second failure: 2 × base_delay (60s)
    delay2 = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    assert 45.0 <= delay2 <= 75.0, f"Second delay should be ~60s ± 25%, got {delay2}"

    # Third failure: 3 × base_delay (90s)
    delay3 = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    assert 67.5 <= delay3 <= 112.5, f"Third delay should be ~90s ± 25%, got {delay3}"


@pytest.mark.asyncio
async def test_backoff_caps_at_max_delay():
    """Verify backoff delay never exceeds max_delay regardless of failure count."""
    redis = FakeBackoffRedis()
    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 100.0  # Low cap for testing
    ttl = 300

    # Simulate 20 failures to force cap
    for _ in range(20):
        delay = await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )

    # Final delay should be capped at max_delay + jitter
    # Max jitter = 100 * 0.25 = 25, so max possible = 125
    assert delay <= 125.0, f"Delay should be capped at {max_delay} + jitter, got {delay}"


@pytest.mark.asyncio
async def test_jitter_within_bounds(monkeypatch):
    """Verify jitter randomness stays within ±25% bounds."""
    redis = FakeBackoffRedis()
    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 300.0
    ttl = 300

    # Increment counter to 1 (then _tenant_retry_delay increments to 2, so delay = 60s base)
    await redis.incr(f"tenant:{tenant_id}:limiter_backoff")

    # Test maximum jitter (+25%)
    monkeypatch.setattr(random, "uniform", lambda a, b: b)  # Return upper bound
    delay_max = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    # Expected: 60s base (2 failures after incr) + 25% = 75s
    assert 73 <= delay_max <= 77, f"Max jitter should give ~75s, got {delay_max}"

    # Reset counter
    await _reset_tenant_retry_delay(tenant_id=tenant_id, redis_client=redis)

    # Increment once
    await redis.incr(f"tenant:{tenant_id}:limiter_backoff")

    # Test minimum jitter (-25%)
    monkeypatch.setattr(random, "uniform", lambda a, b: a)  # Return lower bound
    delay_min = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    # Expected: 60s base (2 failures) - 25% = 45s
    assert 43 <= delay_min <= 47, f"Min jitter should give ~45s, got {delay_min}"


@pytest.mark.asyncio
async def test_reset_deletes_counter():
    """Verify reset_tenant_retry_delay() deletes the backoff counter."""
    redis = FakeBackoffRedis()
    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 300.0
    ttl = 300

    # Increment counter to 5
    for _ in range(5):
        await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )

    # Verify counter is at 5
    key = f"tenant:{tenant_id}:limiter_backoff"
    assert redis.store.get(key) == 5

    # Reset counter
    await _reset_tenant_retry_delay(tenant_id=tenant_id, redis_client=redis)

    # Verify counter deleted
    assert key not in redis.store, "Counter should be deleted after reset"

    # Next increment should return failures=1 (fresh start)
    delay = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    # Should be base_delay ± jitter (first failure)
    assert 22.5 <= delay <= 37.5, f"After reset, should return ~30s, got {delay}"
    assert redis.store.get(key) == 1, "Counter should restart at 1 after reset"


@pytest.mark.asyncio
async def test_incr_success_expire_failure_returns_base_delay():
    """Verify fallback to base_delay when expire() fails but incr() succeeds."""
    redis = FakeBackoffRedis()
    redis.fail_expire_once = True  # Expire will fail on first call

    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 300.0
    ttl = 300

    # First call: incr succeeds, expire fails
    delay1 = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )

    # Should return base_delay due to exception handling
    assert delay1 == base_delay, f"On expire failure, should return base_delay, got {delay1}"

    # BUT counter should still be incremented (persists in Redis)
    key = f"tenant:{tenant_id}:limiter_backoff"
    assert redis.store.get(key) == 1, "Counter should still increment despite expire failure"

    # Second call: both incr and expire succeed
    delay2 = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )

    # Counter is now 2, so delay ≈ 60s ± jitter
    assert 45.0 <= delay2 <= 75.0, f"Second call should show counter=2 (~60s), got {delay2}"


@pytest.mark.asyncio
async def test_ttl_expiry_resets_counter():
    """Verify backoff counter resets when TTL expires (simulated)."""
    redis = FakeBackoffRedis()
    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 300.0
    ttl = 300

    # Increment counter to 5
    for _ in range(5):
        await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )

    # Verify counter is 5
    key = f"tenant:{tenant_id}:limiter_backoff"
    assert redis.store.get(key) == 5

    # Simulate TTL expiry by manually deleting the key
    await redis.delete(key)

    # Next call should treat as failures=1 (fresh start)
    delay_after_expiry = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )

    # Should be base_delay ± jitter
    assert 22.5 <= delay_after_expiry <= 37.5, (
        f"After TTL expiry, should return ~{base_delay}s, got {delay_after_expiry}"
    )
    assert redis.store.get(key) == 1, "Counter should restart at 1 after expiry"


@pytest.mark.asyncio
async def test_backoff_with_no_redis_returns_base_delay():
    """Verify fallback to base_delay when Redis client is None."""
    tenant_id = uuid4()
    base_delay = 30.0
    max_delay = 300.0
    ttl = 300

    # Call with redis_client=None
    delay = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=None,  # No Redis available
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )

    # Should return base_delay without modification
    assert delay == base_delay, f"With no Redis, should return base_delay, got {delay}"
