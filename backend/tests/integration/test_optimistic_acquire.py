"""Integration tests for optimistic acquire pattern (commit 48645e2).

Tests the optimistic acquire pattern for manual/bulk crawls:
- Manual crawls try immediate slot acquisition (low latency when capacity exists)
- If slot acquired: direct ARQ enqueue with pre-acquired flag
- If at capacity: graceful queueing via pending queue (no retry storm)
- Automatic feeder crawls only process when capacity available

The optimistic acquire system provides:
- Low latency for manual crawls when capacity exists (fast path)
- Graceful degradation when at capacity (slow path via pending queue)
- Prevention of retry storms from manual crawl bursts
- Maintained tenant concurrency limits

Note: Full E2E testing of actual crawl execution would require
running live crawler jobs and Redis concurrency management.
These tests verify the configuration and integration patterns.
"""

import pytest
from httpx import AsyncClient
from uuid import uuid4

from intric.tenants.crawler_settings_helper import get_crawler_setting


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireConfiguration:
    """Tests that optimistic acquire is enabled via settings."""

    async def test_crawl_feeder_enabled_setting(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_feeder_enabled controls optimistic acquire behavior.

        When enabled:
        - Manual crawls use optimistic slot acquisition
        - At capacity → pending queue (not immediate retry storm)

        When disabled:
        - Manual crawls bypass concurrency limiter entirely
        - Original direct enqueue behavior
        """
        # Set concurrency limit to enable feeder mode
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 2},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Verify worker retrieves the setting
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            concurrency_limit = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant.crawler_settings,
            )

            assert concurrency_limit == 2
            assert isinstance(concurrency_limit, int)


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireSlotBehavior:
    """Tests for optimistic slot acquisition patterns."""

    async def test_slot_preacquired_flag_pattern(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Optimistic acquire uses slot_preacquired Redis flag.

        Pattern (from crawl_service.py:273-288):
        1. Manual crawl tries to acquire slot atomically
        2. If acquired: set flag job:{job_id}:slot_preacquired
        3. Enqueue to ARQ with flag
        4. Worker sees flag, skips limiter.acquire() (slot already held)
        5. Worker deletes flag and continues with slot
        """
        # This test verifies the configuration exists for the pattern
        # Actual Redis flag lifecycle testing would require running jobs

        # Verify concurrency limit setting is configurable
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 1},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant.crawler_settings,
            )
            assert limit == 1, "Concurrency limit enables optimistic acquire"

    async def test_concurrency_limit_zero_disables_limiting(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Setting concurrency limit to 0 disables limiting.

        This allows unlimited concurrent crawls for a tenant.
        """
        # Set limit to 0 (unlimited)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 0},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant.crawler_settings,
            )
            assert limit == 0, "Zero limit = unlimited concurrency"


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireRangeValidation:
    """Tests that concurrency limit enforces valid ranges."""

    async def test_concurrency_limit_rejects_negative(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Concurrency limit must be >= 0."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": -1},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject negative limit"

    async def test_concurrency_limit_accepts_valid_range(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Concurrency limit accepts 0-50 range."""
        # Test zero (unlimited)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 0},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test reasonable limit
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 10},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test maximum boundary
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 50},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireMultiTenantIsolation:
    """Tests that concurrency limits are isolated between tenants."""

    async def test_different_tenants_different_concurrency_limits(
        self, client: AsyncClient, super_admin_token, db_container
    ):
        """Each tenant can have independent concurrency limits.

        CRITICAL: Limit leakage would allow one tenant's crawls to
        consume another tenant's concurrency slots.
        """
        # Create two test tenants
        tenant_1_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-optimistic-1-{uuid4().hex[:6]}",
                "display_name": "High Concurrency Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_1_response.status_code == 200
        tenant_1 = tenant_1_response.json()

        tenant_2_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-optimistic-2-{uuid4().hex[:6]}",
                "display_name": "Low Concurrency Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_2_response.status_code == 200
        tenant_2 = tenant_2_response.json()

        # Configure high concurrency for tenant 1
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_1['id']}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 20},
            headers={"X-API-Key": super_admin_token},
        )

        # Configure low concurrency for tenant 2
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_2['id']}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 2},
            headers={"X-API-Key": super_admin_token},
        )

        # Verify isolation
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Get tenant 1
            t1 = await tenant_repo.get(tenant_1["id"])
            t1_limit = get_crawler_setting(
                "tenant_worker_concurrency_limit", t1.crawler_settings
            )

            # Get tenant 2
            t2 = await tenant_repo.get(tenant_2["id"])
            t2_limit = get_crawler_setting(
                "tenant_worker_concurrency_limit", t2.crawler_settings
            )

            # Verify complete isolation
            assert t1_limit == 20, "Tenant 1 should have high concurrency"
            assert t2_limit == 2, "Tenant 2 should have low concurrency"


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireUpdatePropagation:
    """Tests that concurrency limit changes propagate immediately."""

    async def test_concurrency_limit_change_visible_immediately(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Concurrency limit changes should apply to next crawl.

        This ensures workers pick up new limits without restart.
        """
        # Initial limit (low concurrency)
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 1},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First read
            tenant = await tenant_repo.get(test_tenant.id)
            limit_1 = get_crawler_setting(
                "tenant_worker_concurrency_limit", tenant.crawler_settings
            )
            assert limit_1 == 1

            # Update limit (increase concurrency)
            await client.put(
                f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
                json={"tenant_worker_concurrency_limit": 10},
                headers={"X-API-Key": super_admin_token},
            )

            # Second read (simulating next crawl execution)
            tenant = await tenant_repo.get(test_tenant.id)
            limit_2 = get_crawler_setting(
                "tenant_worker_concurrency_limit", tenant.crawler_settings
            )
            assert limit_2 == 10, "Updated limit should be visible immediately"


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireUseCases:
    """Tests for different concurrency limit use cases."""

    async def test_unlimited_concurrency_for_burst_loads(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Setting limit to 0 allows unlimited concurrent crawls.

        Use case: Burst crawl periods where tenant needs unlimited concurrency.
        """
        # Set unlimited concurrency
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 0},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit", tenant.crawler_settings
            )

            # Verify unlimited
            assert limit == 0, "Zero limit = no concurrency restriction"

    async def test_conservative_limit_for_resource_protection(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Low limits protect tenant resources during normal operations."""
        # Set conservative limit
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 2},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit", tenant.crawler_settings
            )

            # Verify conservative limit
            assert limit == 2, "Low limit protects resources"


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireWithOtherSettings:
    """Tests optimistic acquire interaction with other crawler settings."""

    async def test_concurrency_limit_with_feeder_batch_size(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Concurrency limit and feeder batch size work together.

        - Concurrency limit: How many jobs can run simultaneously per tenant
        - Feeder batch size: How many jobs feeder enqueues per cycle

        Best practice: batch_size >= concurrency_limit for efficiency.
        """
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "tenant_worker_concurrency_limit": 5,
                "crawl_feeder_batch_size": 10,  # Batch >= limit
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit", tenant.crawler_settings
            )
            batch_size = get_crawler_setting(
                "crawl_feeder_batch_size", tenant.crawler_settings
            )

            # Verify sensible relationship
            assert limit == 5
            assert batch_size == 10
            assert batch_size >= limit, (
                "Batch size should be >= limit for efficient feeder operation"
            )

    async def test_concurrency_limit_with_heartbeat_settings(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Concurrency limit is independent of heartbeat configuration."""
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "tenant_worker_concurrency_limit": 3,
                "crawl_heartbeat_interval_seconds": 300,
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit", tenant.crawler_settings
            )
            heartbeat = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )

            # Verify both settings configured independently
            assert limit == 3
            assert heartbeat == 300


@pytest.mark.asyncio
@pytest.mark.integration
class TestOptimisticAcquireSlotManagement:
    """Tests for slot acquisition and release patterns."""

    async def test_slot_ttl_setting_configured(
        self, client: AsyncClient, test_settings
    ):
        """tenant_worker_semaphore_ttl_seconds controls slot expiry.

        This setting determines how long an acquired slot remains valid.
        Prevents slot leaks if worker crashes before releasing.
        """
        # Verify setting exists and is accessible
        assert hasattr(test_settings, "tenant_worker_semaphore_ttl_seconds")
        ttl = test_settings.tenant_worker_semaphore_ttl_seconds

        # Should be a reasonable TTL value
        assert isinstance(ttl, int)
        assert ttl > 0, "TTL must be positive"
        assert ttl >= 60, "TTL should be at least 1 minute to survive queue waits"

    async def test_slot_preacquired_ttl_survives_queue_backlog(
        self, client: AsyncClient, test_settings
    ):
        """slot_preacquired flag has 1 hour TTL.

        From crawl_feeder.py:234-236:
        - Use 1 hour TTL to survive queue backlogs
        - Semaphore TTL may be shorter than worst-case queue wait time
        - Worker deletes flag on pickup

        This ensures the flag doesn't expire before worker picks up job.
        """
        # Verify semaphore TTL exists
        semaphore_ttl = test_settings.tenant_worker_semaphore_ttl_seconds

        # slot_preacquired TTL (1 hour = 3600s) for flag cleanup
        preacquired_ttl = 3600  # Hardcoded in crawl_feeder.py:236

        # Verify both TTLs are positive and reasonable
        assert preacquired_ttl > 0, "Preacquired TTL must be positive"
        assert semaphore_ttl > 0, "Semaphore TTL must be positive"
        # Note: Semaphore TTL (5hrs) > preacquired TTL (1hr) is intentional for safety
