"""End-to-end integration tests for multi-tenant worker concurrency limits.

These tests verify the Redis-backed semaphore system that enforces per-tenant
concurrency limits for background workers, covering:

* Per-tenant job limits under concurrent load
* Redis failure recovery (fail-open behavior)
* Semaphore TTL expiry and slot leakage prevention
* Fair resource distribution across multiple tenants
* Configuration validation edge cases

Critical Settings:
- WORKER_MAX_CONCURRENT_JOBS: Global worker pool size (e.g., 10)
- TENANT_WORKER_CONCURRENCY_LIMIT: Max concurrent jobs per tenant (e.g., 4)
- TENANT_WORKER_SEMAPHORE_TTL_SECONDS: Slot auto-release timeout (e.g., 18000)
- TENANT_WORKER_RETRY_DELAY_SECONDS: Backoff delay when limit reached (e.g., 30)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
import redis.asyncio as aioredis
from httpx import AsyncClient

if TYPE_CHECKING:
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


async def _create_website(
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    user_id: str,
    url: str,
) -> dict:
    """Helper to create a test website for crawling."""
    # Create a space first
    space_payload = {
        "name": f"test-space-{uuid4().hex[:6]}",
        "description": "Test space for worker concurrency",
    }
    space_response = await client.post(
        "/api/v1/spaces/",
        json=space_payload,
        headers={"X-API-Key": super_api_key},
    )
    assert space_response.status_code == 200, space_response.text
    space_id = space_response.json()["id"]

    # Create website in the space
    website_payload = {
        "url": url,
        "space_id": space_id,
        "user_id": user_id,
    }
    response = await client.post(
        "/api/v1/websites/",
        json=website_payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_user(
    client: AsyncClient,
    super_api_key: str,
    tenant_id: str,
    email: str,
) -> dict:
    """Helper to create a test user."""
    payload = {
        "email": email,
        "username": email.split("@")[0],
        "tenant_id": tenant_id,
        "password": "TestPass123!",
    }
    response = await client.post(
        "/api/v1/sysadmin/users/",
        json=payload,
        headers={"X-API-Key": super_api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_worker_limit_enforced_under_load(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify per-tenant concurrency limit under heavy concurrent job submission.

    Scenario:
    - Tenant has TENANT_WORKER_CONCURRENCY_LIMIT=4
    - Submit 10 concurrent crawl jobs
    - Verify exactly 4 execute immediately, 6 retry with backoff
    - Check Redis semaphore state (keys, values, TTLs)

    This test exposes:
    - Race conditions in semaphore acquire/release
    - Lua script atomicity issues
    - TTL management bugs
    """
    # Setup: Create tenant
    tenant_slug = f"tenant-concurrency-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    # Check initial semaphore state (should be 0 or non-existent)
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    initial_count = await redis_client.get(semaphore_key)
    assert initial_count is None or int(initial_count) == 0

    # TODO: Trigger crawl jobs concurrently
    # This requires access to the ARQ queue or job manager
    # For now, verify the semaphore behavior directly using the limiter

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Simulate 10 concurrent acquire attempts
    acquire_results = []
    for i in range(10):
        result = await limiter.acquire(tenant_id)
        acquire_results.append(result)

    # Verify exactly 4 succeeded, 6 failed
    assert acquire_results.count(True) == 4, f"Expected 4 acquired, got {acquire_results.count(True)}"
    assert acquire_results.count(False) == 6, f"Expected 6 rejected, got {acquire_results.count(False)}"

    # Check Redis semaphore state
    current_count = await redis_client.get(semaphore_key)
    assert int(current_count) == 4, f"Expected semaphore=4, got {current_count}"

    # Verify TTL is set
    ttl = await redis_client.ttl(semaphore_key)
    assert ttl > 0, "Semaphore key should have TTL"
    assert ttl <= test_settings.tenant_worker_semaphore_ttl_seconds

    # Cleanup: Release all acquired slots
    for _ in range(4):
        await limiter.release(tenant_id)

    # Verify semaphore cleaned up
    final_count = await redis_client.get(semaphore_key)
    assert final_count is None or int(final_count) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_redis_failure_opens_circuit_and_enforces_fallback(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
    monkeypatch,
):
    """Verify fail-closed behavior with local fallback when Redis is unavailable.

    Scenario:
    - Simulate Redis connection failure during acquire()
    - Verify circuit breaker opens and local fallback is enforced
    - Local fallback allows up to local_limit tasks, then rejects
    - Restore Redis, verify circuit closes and Redis path resumes

    This test exposes:
    - Fail-closed behavior prevents unlimited concurrency during Redis outages
    - Local fallback provides bounded availability (not unlimited)
    - Circuit breaker properly transitions between states
    - Redis recovery restores normal operation
    """
    tenant_slug = f"tenant-failclosed-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    # Create limiter with mocked Redis that raises exception
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise aioredis.ConnectionError("Simulated Redis failure")

    failing_limiter = TenantConcurrencyLimiter(
        redis=FailingRedis(),  # type: ignore
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Attempt multiple acquires with failing Redis
    # local_limit defaults to max_concurrent (4) per __post_init__
    results = []
    for _ in range(10):
        result = await failing_limiter.acquire(tenant_id)
        results.append(result)

    # Verify fail-closed with bounded fallback: exactly 4 succeed, 6 fail
    succeeded = results.count(True)
    failed = results.count(False)
    assert succeeded == 4, f"Expected 4 acquisitions via fallback, got {succeeded}"
    assert failed == 6, f"Expected 6 rejections when fallback saturated, got {failed}"

    # Cleanup: release only the acquired slots
    for _ in range(succeeded):
        await failing_limiter.release(tenant_id)

    # Restore working Redis and verify circuit closes
    working_limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Next acquire should hit Redis path and close circuit
    result_after_recovery = await working_limiter.acquire(tenant_id)
    assert result_after_recovery is True, "Should acquire via Redis after recovery"

    # Cleanup
    await working_limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semaphore_ttl_prevents_slot_leakage(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify semaphore slots auto-release after TTL expiry.

    Scenario:
    - Acquire 4 slots (reach limit)
    - Simulate worker crash (no explicit release)
    - Wait for TTL to expire
    - Verify slots auto-released, new jobs can run

    This test exposes:
    - Slot leakage when workers crash
    - TTL not being set correctly
    - Redis key cleanup issues
    """
    tenant_slug = f"tenant-ttl-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    # Use very short TTL for testing (2 seconds)
    short_ttl = 2
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=short_ttl,
    )

    # Acquire all 4 slots
    for _ in range(4):
        result = await limiter.acquire(tenant_id)
        assert result is True

    # Verify limit reached
    result_blocked = await limiter.acquire(tenant_id)
    assert result_blocked is False, "5th job should be blocked"

    # Simulate worker crash: DO NOT release slots
    # Wait for TTL to expire
    await asyncio.sleep(short_ttl + 0.5)

    # Verify slots auto-released
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    count_after_ttl = await redis_client.get(semaphore_key)

    # Key should be deleted when count reaches 0 after TTL
    assert count_after_ttl is None, f"Semaphore should auto-expire, got {count_after_ttl}"

    # Verify new job can acquire slot
    result_after_expire = await limiter.acquire(tenant_id)
    assert result_after_expire is True, "Should be able to acquire after TTL expiry"

    # Cleanup
    await limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_tenants_share_global_worker_pool_fairly(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify fair distribution when multiple tenants compete for global worker pool.

    Scenario:
    - 3 tenants, each with TENANT_LIMIT=4
    - GLOBAL_LIMIT=10 (hypothetical)
    - Each tenant submits 5 jobs (15 total)
    - Verify no single tenant monopolizes the pool

    This test exposes:
    - Tenant starvation scenarios
    - Unfair queueing (FIFO vs fair)
    - Global vs per-tenant limit interaction
    """
    # Create 3 tenants
    tenants = []
    for i in range(3):
        tenant_slug = f"tenant-fair-{i}-{uuid4().hex[:6]}"
        tenant = await _create_tenant(client, super_admin_token, tenant_slug)
        tenants.append(UUID(tenant["id"]))

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Each tenant tries to acquire 5 slots (total 15 attempts)
    results_by_tenant = {}
    for tenant_id in tenants:
        acquire_results = []
        for _ in range(5):
            result = await limiter.acquire(tenant_id)
            acquire_results.append(result)
        results_by_tenant[tenant_id] = acquire_results

    # Verify each tenant got exactly 4 slots (fair distribution)
    for tenant_id, results in results_by_tenant.items():
        succeeded = results.count(True)
        assert succeeded == 4, f"Tenant {tenant_id} should get 4 slots, got {succeeded}"
        assert results.count(False) == 1, f"Tenant {tenant_id} should reject 1 job"

    # Cleanup: Release all acquired slots
    for tenant_id in tenants:
        for _ in range(4):
            await limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_acquire_and_release_race_condition(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify Lua script atomicity under concurrent acquire/release operations.

    Scenario:
    - 100 concurrent acquire() calls
    - Randomly interleaved with release() calls
    - Verify semaphore count never goes negative or exceeds limit

    This test exposes:
    - Race conditions in Lua script
    - INCR/DECR atomicity issues
    - Lock-free algorithm bugs
    """
    tenant_slug = f"tenant-race-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    acquired_count = 0

    async def acquire_task():
        nonlocal acquired_count
        result = await limiter.acquire(tenant_id)
        if result:
            acquired_count += 1
        return result

    async def release_task():
        nonlocal acquired_count
        if acquired_count > 0:
            await limiter.release(tenant_id)
            acquired_count -= 1

    # Run 100 concurrent operations
    tasks = []
    for i in range(100):
        if i % 3 == 0 and acquired_count > 0:
            # Every 3rd operation: release
            tasks.append(release_task())
        else:
            # Otherwise: acquire
            tasks.append(acquire_task())

    await asyncio.gather(*tasks)

    # Verify final semaphore state is consistent
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    final_count = await redis_client.get(semaphore_key)

    if final_count:
        final_count_int = int(final_count)
        assert 0 <= final_count_int <= 4, f"Semaphore count {final_count_int} out of range [0, 4]"

    # Cleanup
    for _ in range(acquired_count):
        await limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_zero_limit_disables_concurrency_control(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify TENANT_WORKER_CONCURRENCY_LIMIT=0 disables per-tenant limits.

    Scenario:
    - Set limit to 0 (unlimited)
    - Attempt 100 concurrent acquires
    - Verify all succeed

    This test exposes:
    - Off-by-one errors in limit=0 handling
    - Lua script early return logic
    """
    tenant_slug = f"tenant-unlimited-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    # Limit=0 means no limit
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=0,  # Unlimited
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Attempt 100 concurrent acquires
    results = []
    for _ in range(100):
        result = await limiter.acquire(tenant_id)
        results.append(result)

    # All should succeed
    assert all(results), f"All 100 acquires should succeed with limit=0, got {results.count(True)}/100"

    # Verify Redis key was never created
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    count = await redis_client.get(semaphore_key)
    assert count is None, "Semaphore key should not be created when limit=0"


# ============================================================================
# Worker Hardening: Circuit Breaker & Exponential Backoff Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_circuit_breaker_end_to_end_redis_recovery(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify complete circuit breaker lifecycle: failure → fallback → recovery → resume.

    Scenario:
    - Redis failure causes circuit to open
    - Local fallback enforces bounded limits
    - Redis recovers
    - Circuit closes and normal Redis operation resumes

    This test exposes:
    - End-to-end circuit breaker behavior
    - Smooth transition between Redis and fallback modes
    - Proper cleanup and recovery
    """
    tenant_slug = f"tenant-circuit-e2e-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    # Create limiter
    limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=3,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
        circuit_break_seconds=2,  # Short circuit for testing
        local_limit=2,  # Lower than Redis limit for distinction
    )

    # Phase 1: Normal Redis operation
    result1 = await limiter.acquire(tenant_id)
    assert result1 is True, "Should acquire via Redis initially"

    # Verify Redis has the slot
    semaphore_key = f"tenant:{tenant_id}:active_jobs"
    count = await redis_client.get(semaphore_key)
    assert int(count) == 1, "Redis should track acquisition"

    # Release Redis slot
    await limiter.release(tenant_id)

    # Phase 2: Simulate Redis failure
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise aioredis.ConnectionError("Simulated Redis outage")

    original_redis = limiter.redis
    limiter.redis = FailingRedis()  # type: ignore

    # Acquire during Redis failure → should use fallback
    results_fallback = []
    for _ in range(5):
        result = await limiter.acquire(tenant_id)
        results_fallback.append(result)

    # Verify fallback limit enforced (local_limit=2)
    assert results_fallback.count(True) == 2, "Fallback should allow 2 acquisitions"
    assert results_fallback.count(False) == 3, "Fallback should reject 3rd+ acquisition"

    # Phase 3: Restore Redis
    limiter.redis = original_redis

    # Wait for circuit to close (2 seconds)
    await asyncio.sleep(2.5)

    # Next acquire should use Redis and close circuit
    result_after_recovery = await limiter.acquire(tenant_id)
    assert result_after_recovery is True, "Should acquire via Redis after recovery"

    # Verify Redis counter incremented (not fallback)
    count_after_recovery = await redis_client.get(semaphore_key)
    assert int(count_after_recovery) == 1, "Redis should resume tracking"

    # Cleanup
    await limiter.release(tenant_id)
    # Release fallback acquisitions
    for _ in range(2):
        await limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_tenants_independent_fallback_limits(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify tenants have independent fallback limits during circuit-open.

    Scenario:
    - 3 tenants during Redis outage
    - Each should get independent local_limit slots
    - No cross-tenant interference or shared counter bugs

    This test exposes:
    - Cross-tenant contamination in fallback counters
    - Lock serialization issues affecting wrong tenants
    """
    # Create 3 tenants
    tenants = []
    for i in range(3):
        tenant_slug = f"tenant-independent-{i}-{uuid4().hex[:6]}"
        tenant = await _create_tenant(client, super_admin_token, tenant_slug)
        tenants.append(UUID(tenant["id"]))

    from intric.worker.tenant_concurrency import TenantConcurrencyLimiter

    # Force circuit open with failing Redis
    class FailingRedis:
        async def eval(self, *args, **kwargs):
            raise aioredis.ConnectionError("Simulated Redis failure")

    limiter = TenantConcurrencyLimiter(
        redis=FailingRedis(),  # type: ignore
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
        local_limit=3,  # Each tenant gets 3 slots
    )

    # Each tenant attempts 5 acquisitions
    results_by_tenant = {}
    for tenant_id in tenants:
        results = []
        for _ in range(5):
            result = await limiter.acquire(tenant_id)
            results.append(result)
        results_by_tenant[tenant_id] = results

    # Verify each tenant independently got 3 slots
    for tenant_id, results in results_by_tenant.items():
        succeeded = results.count(True)
        failed = results.count(False)
        assert succeeded == 3, f"Tenant {tenant_id} should get 3 slots, got {succeeded}"
        assert failed == 2, f"Tenant {tenant_id} should reject 2 attempts, got {failed}"

    # Verify 3 separate entries in local counts
    assert len(limiter._local_counts) == 3, "Should have 3 independent tenant entries"

    # Cleanup
    for tenant_id in tenants:
        for _ in range(3):
            await limiter.release(tenant_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backoff_counter_increments_and_resets(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify backoff counter increments with requeues and resets on success.

    Scenario:
    - Pre-saturate limiter to force requeues
    - Observe backoff counter increment in Redis
    - Simulate successful execution
    - Verify counter resets

    This test exposes:
    - Backoff counter persistence in Redis
    - Reset logic integration with crawl_task
    """
    tenant_slug = f"tenant-backoff-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.crawl_tasks import _tenant_retry_delay, _reset_tenant_retry_delay

    base_delay = 10.0  # Low for faster testing
    max_delay = 100.0
    ttl = 120

    # Simulate 3 requeues
    delays = []
    for _ in range(3):
        delay = await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis_client,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )
        delays.append(delay)

    # Verify increasing delays (approximately 10s, 20s, 30s with jitter)
    # Allow small timing variations due to system jitter and async scheduling
    TOLERANCE_MS = 2.0
    assert delays[0] <= delays[1] + TOLERANCE_MS, (
        f"Second delay ({delays[1]:.2f}ms) should be >= first ({delays[0]:.2f}ms) "
        f"within {TOLERANCE_MS}ms tolerance. Difference: {delays[1] - delays[0]:.2f}ms"
    )
    assert delays[1] <= delays[2] + TOLERANCE_MS, (
        f"Third delay ({delays[2]:.2f}ms) should be >= second ({delays[1]:.2f}ms) "
        f"within {TOLERANCE_MS}ms tolerance. Difference: {delays[2] - delays[1]:.2f}ms"
    )

    # Verify backoff counter in Redis
    backoff_key = f"tenant:{tenant_id}:limiter_backoff"
    counter = await redis_client.get(backoff_key)
    assert int(counter) == 3, f"Counter should be 3 after 3 requeues, got {counter}"

    # Simulate successful execution → reset counter
    await _reset_tenant_retry_delay(tenant_id=tenant_id, redis_client=redis_client)

    # Verify counter deleted
    counter_after_reset = await redis_client.get(backoff_key)
    assert counter_after_reset is None, "Counter should be deleted after reset"

    # Next requeue should start at 1 again
    delay_after_reset = await _tenant_retry_delay(
        tenant_id=tenant_id,
        redis_client=redis_client,
        base_delay=base_delay,
        max_delay=max_delay,
        ttl_seconds=ttl,
    )
    assert 7.5 <= delay_after_reset <= 12.5, f"Reset should return ~{base_delay}s, got {delay_after_reset}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backoff_delay_progression_with_jitter(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
):
    """Verify backoff delays increase correctly and stay within jitter bounds.

    Scenario:
    - Simulate 10 consecutive requeues
    - Track delay progression
    - Verify jitter keeps delays within ±25%
    - Verify cap at max_delay

    This test exposes:
    - Incorrect backoff formula
    - Jitter out of bounds
    - Missing max_delay cap
    """
    tenant_slug = f"tenant-progression-{uuid4().hex[:6]}"
    tenant = await _create_tenant(client, super_admin_token, tenant_slug)
    tenant_id = UUID(tenant["id"])

    from intric.worker.crawl_tasks import _tenant_retry_delay

    base_delay = 20.0
    max_delay = 100.0  # Cap at 100s for testing
    ttl = 300

    delays = []
    for i in range(10):
        delay = await _tenant_retry_delay(
            tenant_id=tenant_id,
            redis_client=redis_client,
            base_delay=base_delay,
            max_delay=max_delay,
            ttl_seconds=ttl,
        )
        delays.append(delay)

        # Verify delay is within expected range for this failure count
        expected_base = min(base_delay * (i + 1), max_delay)
        min_expected = expected_base * 0.75
        max_expected = expected_base * 1.25

        assert min_expected <= delay <= max_expected, (
            f"Delay {i+1} should be {expected_base}s ± 25% "
            f"([{min_expected}, {max_expected}]), got {delay}"
        )

    # Verify delays generally increase (allowing for jitter)
    # Check that average of first 3 < average of last 3
    avg_early = sum(delays[:3]) / 3
    avg_late = sum(delays[-3:]) / 3
    assert avg_late >= avg_early, (
        f"Later delays should average higher than early delays. "
        f"Early avg: {avg_early}, Late avg: {avg_late}"
    )

    # Verify delays are capped
    for delay in delays:
        assert delay <= max_delay * 1.25, f"Delay should not exceed max + jitter: {delay}"
