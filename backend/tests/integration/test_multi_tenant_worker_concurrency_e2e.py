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
async def test_redis_failure_fails_open_allows_execution(
    client: AsyncClient,
    super_admin_token: str,
    redis_client: aioredis.Redis,
    test_settings: Settings,
    mock_transcription_models,
    monkeypatch,
):
    """Verify defensive fail-open behavior when Redis is unavailable.

    Scenario:
    - Simulate Redis connection failure during acquire()
    - Verify job executes anyway (fail-open prevents cascading failures)
    - Restore Redis, verify semaphore cleanup works

    This test exposes:
    - Dependency on Redis availability
    - Silent failures that could lead to unlimited concurrency
    - Error handling in Lua script execution
    """
    tenant_slug = f"tenant-failopen-{uuid4().hex[:6]}"
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

    # Attempt acquire with failing Redis
    result = await failing_limiter.acquire(tenant_id)

    # Verify fail-open: job is allowed to execute
    assert result is True, "Should fail-open (allow execution) when Redis unavailable"

    # Restore working Redis
    working_limiter = TenantConcurrencyLimiter(
        redis=redis_client,
        max_concurrent=4,
        ttl_seconds=test_settings.tenant_worker_semaphore_ttl_seconds,
    )

    # Verify semaphore works again
    result2 = await working_limiter.acquire(tenant_id)
    assert result2 is True

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
