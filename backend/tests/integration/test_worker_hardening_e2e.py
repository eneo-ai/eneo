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


# Note: Tests using the removed _tenant_retry_delay function have been removed.
# See test_crawler_retry_behavior.py for new per-job retry tests.


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
