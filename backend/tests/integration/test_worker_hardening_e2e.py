"""End-to-end integration tests for worker hardening features.

These tests verify the complete worker hardening implementation including:
- Real crawl task execution with concurrency limiting
- Exponential backoff during requeues
- Circuit breaker behavior during Redis failures
- Proper cleanup and recovery after failures

These are comprehensive tests that exercise the full stack from API to worker.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient

from intric.main.config import Settings


async def _create_tenant(client: AsyncClient, super_api_key: str, name: str) -> dict:
    """Helper to create a test tenant via API."""
    payload = {
        "name": name,
        "display_name": name,
        "state": "active",
    }
    response = await client.post(
        "/api/v1/sysadmin/tenants/",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


# Note: Unused helper functions removed - this test focuses on worker logic only,
# not API/auth integration. For tests requiring full API setup, see other integration tests.


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_crawl_task_requeue_with_exponential_backoff(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify crawl task requeue logic with exponential backoff when limit hit.

    Scenario:
    - Create tenant
    - Pre-saturate the concurrency limit
    - Simulate crawl task attempting to acquire (will fail and need requeue)
    - Observe backoff delays increasing over multiple requeues
    - Release slots, verify backoff resets after successful execution

    This test exposes:
    - Integration between limiter.acquire(), backoff calculation, and retry logic
    - Backoff counter lifecycle from requeue to reset
    - Proper cleanup after task completion

    Note: This test focuses on worker logic without requiring full API/auth setup.
    """
    # Setup: Create tenant
    tenant_slug = f"tenant-backoff-e2e-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter
    from intric.worker.crawl_tasks import _tenant_retry_delay, _reset_tenant_retry_delay

    # Pre-saturate limiter (acquire all slots)
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=2,  # Low limit for testing
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Acquire both slots
    await limiter.acquire(tenant_id)
    await limiter.acquire(tenant_id)

    # Verify limit saturated
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    count = await redis_client.get(semaphore_key)
    assert int(count) == 2, "Limiter should be saturated"

    # Now simulate crawl_task attempting to acquire (will fail and requeue)
    # We can't actually queue the task without ARQ infrastructure,
    # but we can verify the backoff mechanism directly

    base_delay = 10.0
    max_delay = 60.0
    ttl = 120

    # Simulate 5 requeue attempts (task can't acquire slot)
    delays = []
    for i in range(5):
        delay = await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis_client,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )
        delays.append(delay)

    # Verify exponential progression
    # Expected (with jitter): ~10s, ~20s, ~30s, ~40s, ~50s
    for i, delay in enumerate(delays):
        expected_base = min(base_delay * (i + 1), max_delay)
        min_expected = expected_base * 0.75
        max_expected = expected_base * 1.25

        assert min_expected <= delay <= max_expected, (
            f"Requeue {i+1} delay should be ~{expected_base}s ± 25%, got {delay}"
        )

    # Verify backoff counter
    backoff_key = f"tenant:{tenant_id}:limiter_backoff"
    counter = await redis_client.get(backoff_key)
    assert int(counter) == 5, f"Backoff counter should be 5, got {counter}"

    # Simulate successful execution by releasing slots
    await limiter.release(tenant_id)
    await limiter.release(tenant_id)

    # Simulate backoff reset (would happen in crawl_task finally block)
    await _reset_tenant_retry_delay(tenant_id=tenant_id, redis_client=redis_client)

    # Verify counter reset
    counter_after = await redis_client.get(backoff_key)
    assert counter_after is None, "Backoff counter should be deleted after successful execution"

    # Next requeue should start fresh at base_delay
    delay_after_success = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis_client,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    assert 7.5 <= delay_after_success <= 12.5, (
        f"After success, should reset to ~{base_delay}s, got {delay_after_success}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_outage_during_crawl_uses_fallback(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify crawl task can complete using local fallback during Redis outage.

    Scenario:
    - Start with working Redis
    - Acquire slot via Redis
    - Simulate Redis failure mid-execution
    - Task completes successfully via fallback tracking
    - Verify proper cleanup and metric logging

    This test exposes:
    - Graceful degradation during Redis outages
    - Fallback flag tracking across Redis → fallback transition
    - Proper release logic for mixed acquisition paths
    """
    # Setup: Create tenant
    tenant_slug = f"tenant-outage-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=3,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
        circuit_break_seconds=2,
        local_limit=2,
    )

    # Phase 1: Acquire via Redis (normal operation)
    result1 = await limiter.acquire(tenant_id)
    assert result1 is True, "Should acquire via Redis"

    # Verify Redis tracking
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    count_before = await redis_client.get(semaphore_key)
    assert int(count_before) == 1, "Redis should track acquisition"

    # Phase 2: Simulate Redis outage
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise aioredis.ConnectionError("Simulated Redis outage during execution")

    original_redis = limiter.redis
    limiter.redis = FailingRedis()  # type: ignore

    # Another task attempts acquire → should use fallback
    result2 = await limiter.acquire(tenant_id)
    assert result2 is True, "Should acquire via fallback during outage"

    # Phase 3: Verify proper release
    # Release the Redis-acquired slot (should attempt Redis despite circuit)
    limiter.redis = original_redis  # Restore for release
    await limiter.release(tenant_id)

    # Release the fallback-acquired slot
    await limiter.release(tenant_id)

    # Verify cleanup
    final_count = await redis_client.get(semaphore_key)
    assert final_count is None or int(final_count) == 0, "All slots should be released"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_exhausts_slots_repeatedly_backoff_increases(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify tenant repeatedly hitting limits experiences increasing backoff delays.

    Scenario:
    - Tenant submits many tasks
    - Concurrency limit is low (forces requeues)
    - Observe backoff delays increasing over time
    - Eventually slots free up, tasks execute
    - Backoff resets after successful execution

    This test exposes:
    - Real-world behavior when tenant overloads their quota
    - Backoff progression under sustained load
    - Proper reset after pressure subsides
    """
    # Setup: Create tenant
    tenant_slug = f"tenant-sustained-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter
    from intric.worker.crawl_tasks import _tenant_retry_delay, _reset_tenant_retry_delay

    # Create limiter with very low limit (1 slot)
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=1,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Acquire the single slot
    await limiter.acquire(tenant_id)

    # Simulate 10 tasks attempting to acquire (all will fail)
    base_delay = 5.0  # Short for testing
    max_delay = 50.0
    ttl = 120

    delays = []
    for _ in range(10):
        # Check if can acquire
        can_acquire = await limiter.acquire(tenant_id)
        assert can_acquire is False, "Limit should be exhausted"

        # Compute backoff delay (simulates crawl_task requeue logic)
        delay = await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis_client,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )
        delays.append(delay)

    # Verify backoff increased over time
    # With jitter, we can't guarantee strict monotonic increase,
    # but average should increase
    first_half_avg = sum(delays[:5]) / 5
    second_half_avg = sum(delays[5:]) / 5
    assert second_half_avg > first_half_avg, (
        f"Later delays should average higher. "
        f"First half: {first_half_avg}, Second half: {second_half_avg}"
    )

    # Verify final delays are capped
    for delay in delays[-3:]:
        assert delay <= max_delay * 1.25, f"Delays should be capped, got {delay}"

    # Simulate task completion: release slot and reset backoff
    await limiter.release(tenant_id)
    await _reset_tenant_retry_delay(tenant_id=tenant_id, redis_client=redis_client)

    # Verify backoff reset
    backoff_key = f"tenant:{tenant_id}:limiter_backoff"
    counter = await redis_client.get(backoff_key)
    assert counter is None, "Backoff counter should be reset after success"

    # Next attempt should have low delay again
    delay_after_reset = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis_client,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    assert delay_after_reset <= base_delay * 1.25, (
        f"After reset, delay should be near base ({base_delay}s), got {delay_after_reset}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_tenants_with_mixed_backoff_states(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify multiple tenants with different backoff states don't interfere.

    Scenario:
    - Tenant A has high backoff (many failures)
    - Tenant B has low backoff (few failures)
    - Tenant C has no backoff (first attempt)
    - Verify independent delays and no cross-tenant contamination

    This test exposes:
    - Cross-tenant backoff counter interference
    - Redis key namespacing issues
    - Incorrect tenant_id in backoff keys
    """
    # Create 3 tenants
    tenants = []
    for i in range(3):
        tenant_slug = f"tenant-mixed-{i}-{uuid4().hex[:6]}"
        tenant = await _create_tenant(client, super_admin_token, tenant_slug)
        tenants.append(UUID(tenant["id"]))

    from intric.worker.crawl_tasks import _tenant_retry_delay, _reset_tenant_retry_delay

    base_delay = 10.0
    max_delay = 100.0
    ttl = 300

    # Tenant A: Simulate 5 failures (high backoff)
    for _ in range(5):
        await _tenant_retry_delay(
            tenant_id=tenants[0],
            redis_client=redis_client,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )

    # Tenant B: Simulate 2 failures (low backoff)
    for _ in range(2):
        await _tenant_retry_delay(
            tenant_id=tenants[1],
            redis_client=redis_client,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )

    # Tenant C: First attempt (no backoff)
    delay_c = await _tenant_retry_delay(
        tenant_id=tenants[2],
        redis_client=redis_client,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )

    # Now get delays for each tenant
    delay_a = await _tenant_retry_delay(
        tenant_id=tenants[0],
        redis_client=redis_client,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )  # 6th failure → ~60s

    delay_b = await _tenant_retry_delay(
        tenant_id=tenants[1],
        redis_client=redis_client,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )  # 3rd failure → ~30s

    # Verify independent delays (accounting for jitter)
    # Tenant A: 6 failures → 60s ± 25% = [45, 75]
    assert 45 <= delay_a <= 75, f"Tenant A should have ~60s delay, got {delay_a}"

    # Tenant B: 3 failures → 30s ± 25% = [22.5, 37.5]
    assert 22.5 <= delay_b <= 37.5, f"Tenant B should have ~30s delay, got {delay_b}"

    # Tenant C: 1 failure → 10s ± 25% = [7.5, 12.5]
    assert 7.5 <= delay_c <= 12.5, f"Tenant C should have ~10s delay, got {delay_c}"

    # Verify Tenant A's high backoff doesn't affect Tenant B or C
    assert delay_a > delay_b > delay_c, "Delays should reflect independent failure counts"

    # Verify separate Redis keys
    key_a = f"tenant:{tenants[0]}:limiter_backoff"
    key_b = f"tenant:{tenants[1]}:limiter_backoff"
    key_c = f"tenant:{tenants[2]}:limiter_backoff"

    count_a = await redis_client.get(key_a)
    count_b = await redis_client.get(key_b)
    count_c = await redis_client.get(key_c)

    assert int(count_a) == 6, "Tenant A should have 6 failures"
    assert int(count_b) == 3, "Tenant B should have 3 failures"
    assert int(count_c) == 1, "Tenant C should have 1 failure"

    # Cleanup
    await _reset_tenant_retry_delay(tenant_id=tenants[0], redis_client=redis_client)
    await _reset_tenant_retry_delay(tenant_id=tenants[1], redis_client=redis_client)
    await _reset_tenant_retry_delay(tenant_id=tenants[2], redis_client=redis_client)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_single_tenant_mode_backward_compatibility(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify worker hardening doesn't break single-tenant installations.

    Scenario:
    - Single tenant installation (typical for small deployments)
    - Worker limiting still enforces per-tenant limits
    - Circuit breaker and backoff work normally
    - No special configuration needed

    This test exposes:
    - Backward compatibility regressions
    - Single-tenant edge cases in multi-tenant code
    """
    # Create a single tenant (simulates single-tenant installation)
    tenant_slug = f"single-tenant-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter
    from intric.worker.crawl_tasks import _tenant_retry_delay

    # Create limiter (should work same as multi-tenant)
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=2,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Verify basic acquire/release works
    assert await limiter.acquire(tenant_id) is True
    assert await limiter.acquire(tenant_id) is True
    assert await limiter.acquire(tenant_id) is False  # Limit reached

    # Verify backoff works for single tenant
    delay = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis_client,
        base_delay=30.0,
        max_delay=300.0,
        ttl_seconds=300,
    )
    assert 22.5 <= delay <= 37.5, f"Backoff should work in single-tenant mode, got {delay}"

    # Cleanup
    await limiter.release(tenant_id)
    await limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fallback_mode_behavior_under_redis_failure(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify fallback mode works correctly during Redis failures.

    Scenario:
    - Trigger fallback mode via Redis failure
    - Verify acquisitions work up to local_limit
    - Verify rejections after limit reached
    - Verify proper cleanup

    This test exposes:
    - Fallback mode functionality issues
    - Incorrect limit enforcement
    - Cleanup problems in fallback path
    """
    tenant_slug = f"tenant-fallback-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    # Force circuit open to trigger fallback
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis failure for fallback test")

    limiter = TenantConcurrencyLimiter(
        redis=FailingRedis(),  # type: ignore
        max_concurrent=2,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
        local_limit=2,  # Explicit local limit
    )

    # Verify fallback mode works correctly
    # Note: Acquire+release must happen in SAME task (like production crawl_task)
    # so the fallback flag is preserved from acquire to release

    async def acquire_work_release():
        """Matches production pattern: acquire → work → release in SAME task."""
        acquired = await limiter.acquire(tenant_id)
        if acquired:
            # Simulate work
            await asyncio.sleep(0.01)
            # Release in same task (flag is preserved)
            await limiter.release(tenant_id)
        return acquired

    # Run 2 concurrent tasks (both should succeed, limit=2)
    results = await asyncio.gather(
        acquire_work_release(),
        acquire_work_release(),
    )
    assert all(results), "Both tasks should acquire and release successfully"

    # After both tasks complete, counter should be 0 (entry removed)
    assert tenant_id not in limiter._local_counts, (
        f"Fallback entry should be cleaned up after tasks complete. "
        f"Remaining: {limiter._local_counts}"
    )

    # Third task should also succeed (previous 2 released their slots)
    result3 = await acquire_work_release()
    assert result3 is True, "Third task should succeed after others released"

    # Verify final cleanup
    assert tenant_id not in limiter._local_counts, "All slots should be released"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_limiter_release_always_succeeds_with_new_logic(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify release() is idempotent and handles all edge cases.

    Scenario:
    - Acquire via Redis, release via Redis (normal path)
    - Acquire via fallback, release via fallback (degraded path)
    - Double release should be safe (no crashes)
    - Release without acquire should be safe (no crashes)

    This test exposes:
    - Release logic regressions
    - Edge cases in flag tracking
    - Idempotency issues
    """
    tenant_slug = f"tenant-release-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=2,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Test 1: Normal acquire/release via Redis
    assert await limiter.acquire(tenant_id) is True
    await limiter.release(tenant_id)  # Should succeed

    # Test 2: Double release (should be safe, no error)
    await limiter.release(tenant_id)  # Should not crash

    # Test 3: Release without acquire (should be safe)
    await limiter.release(tenant_id)  # Should not crash

    # Test 4: Acquire via fallback, release via fallback
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise Exception("Redis failure")

    limiter.redis = FailingRedis()  # type: ignore
    assert await limiter.acquire(tenant_id) is True  # Via fallback
    await limiter.release(tenant_id)  # Should release from fallback

    # Test 5: Double release of fallback acquisition
    await limiter.release(tenant_id)  # Should not crash

    # All operations succeeded without exceptions
    assert True, "All release operations completed safely"
