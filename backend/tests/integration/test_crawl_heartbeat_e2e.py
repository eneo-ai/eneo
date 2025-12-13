"""Integration tests for crawl heartbeat pattern (commit 039df17).

Tests the heartbeat pattern added for improved observability:
- crawl_heartbeat_interval_seconds setting (30-3600s, default 300s)
- Settings flow from API through database to worker retrieval
- Heartbeat interval configuration for different tenants
- Multi-tenant isolation of heartbeat settings

The heartbeat pattern provides:
- 5-minute (default) heartbeat to signal job is alive
- Structured summary logging for observability
- Configurable interval per tenant

Note: Full E2E testing of actual heartbeat firing would require running
live crawler jobs. These tests verify the configuration layer that enables
heartbeat functionality.
"""

import pytest
from httpx import AsyncClient

from intric.tenants.crawler_settings_helper import (
    get_crawler_setting,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatConfiguration:
    """Tests that heartbeat interval setting configures correctly."""

    async def test_heartbeat_interval_setting_configured(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_heartbeat_interval_seconds flows from API to worker retrieval.

        This verifies the critical path for heartbeat observability:
        1. Admin sets heartbeat interval via API
        2. Worker retrieves interval from database
        3. Worker uses interval for periodic heartbeat logging
        """
        # Set custom heartbeat interval (10 minutes)
        interval_seconds = 600
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": interval_seconds},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Verify worker can retrieve it (simulating worker job execution)
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # This is exactly how crawl_tasks.py retrieves the heartbeat interval
            configured_interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds",
                tenant.crawler_settings,
            )

            assert configured_interval == interval_seconds
            assert isinstance(configured_interval, int)

    async def test_heartbeat_interval_default_value(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """When not set, heartbeat interval should use environment default.

        The default heartbeat interval provides baseline observability.
        """
        # Reset settings to defaults
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # Should return environment default
            default_interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds",
                tenant.crawler_settings,
            )

            # Verify it's a reasonable heartbeat interval (should be from env settings)
            assert isinstance(default_interval, int)
            assert 30 <= default_interval <= 3600, "Default should be within valid range"


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatRangeValidation:
    """Tests that heartbeat interval enforces its 30-3600 second range."""

    async def test_heartbeat_interval_rejects_below_minimum(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Heartbeat interval must be >= 30 seconds."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 15},  # Below minimum
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject interval below 30s"

    async def test_heartbeat_interval_rejects_above_maximum(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Heartbeat interval must be <= 3600 seconds (1 hour)."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 7200},  # Above maximum
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject interval above 3600s"

    async def test_heartbeat_interval_accepts_valid_range(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Heartbeat interval accepts values within 30-3600 second range."""
        # Test minimum boundary (30 seconds)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 30},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test maximum boundary (1 hour)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 3600},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test default value (5 minutes)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 300},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatMultiTenantIsolation:
    """Tests that heartbeat intervals are isolated between tenants."""

    async def test_different_tenants_different_heartbeat_intervals(
        self, client: AsyncClient, super_admin_token, db_container
    ):
        """Each tenant can have independent heartbeat interval configuration.

        CRITICAL: Heartbeat leakage would cause incorrect observability signals.
        One tenant's heartbeat frequency shouldn't affect another's.
        """
        from uuid import uuid4

        # Create two test tenants
        tenant_1_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-heartbeat-1-{uuid4().hex[:6]}",
                "display_name": "Frequent Heartbeat Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_1_response.status_code == 200
        tenant_1 = tenant_1_response.json()

        tenant_2_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-heartbeat-2-{uuid4().hex[:6]}",
                "display_name": "Infrequent Heartbeat Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_2_response.status_code == 200
        tenant_2 = tenant_2_response.json()

        # Configure frequent heartbeats for tenant 1 (every minute)
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_1['id']}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 60},
            headers={"X-API-Key": super_admin_token},
        )

        # Configure infrequent heartbeats for tenant 2 (every 30 minutes)
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_2['id']}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 1800},
            headers={"X-API-Key": super_admin_token},
        )

        # Verify isolation
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Get tenant 1
            t1 = await tenant_repo.get(tenant_1["id"])
            t1_interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", t1.crawler_settings
            )

            # Get tenant 2
            t2 = await tenant_repo.get(tenant_2["id"])
            t2_interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", t2.crawler_settings
            )

            # Verify complete isolation
            assert t1_interval == 60, "Tenant 1 should have frequent heartbeats"
            assert t2_interval == 1800, "Tenant 2 should have infrequent heartbeats"


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatUpdatePropagation:
    """Tests that heartbeat interval changes propagate immediately."""

    async def test_heartbeat_interval_change_visible_immediately(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Heartbeat interval changes should apply to next crawl job.

        This ensures new interval is picked up without worker restart.
        """
        # Initial heartbeat interval (5 minutes)
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 300},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First read
            tenant = await tenant_repo.get(test_tenant.id)
            interval_1 = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )
            assert interval_1 == 300

            # Update interval (1 minute for faster observability)
            await client.put(
                f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
                json={"crawl_heartbeat_interval_seconds": 60},
                headers={"X-API-Key": super_admin_token},
            )

            # Second read (simulating next job execution)
            tenant = await tenant_repo.get(test_tenant.id)
            interval_2 = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )
            assert interval_2 == 60, "Updated interval should be visible immediately"


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatUseCases:
    """Tests for different heartbeat interval use cases."""

    async def test_short_crawls_use_frequent_heartbeats(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Short crawls benefit from frequent heartbeats for detailed observability."""
        # Set short crawl duration with frequent heartbeats
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_max_length": 300,  # 5 minute crawl
                "crawl_heartbeat_interval_seconds": 30,  # 30 second heartbeats
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            max_length = get_crawler_setting("crawl_max_length", tenant.crawler_settings)
            interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )

            # Verify configuration makes sense
            assert max_length == 300
            assert interval == 30
            assert interval < max_length, "Heartbeat should fire multiple times during crawl"

    async def test_long_crawls_use_infrequent_heartbeats(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Long crawls can use infrequent heartbeats to reduce log volume."""
        # Set long crawl duration with infrequent heartbeats
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_max_length": 7200,  # 2 hour crawl
                "crawl_heartbeat_interval_seconds": 600,  # 10 minute heartbeats
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            max_length = get_crawler_setting("crawl_max_length", tenant.crawler_settings)
            interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )

            # Verify configuration makes sense
            assert max_length == 7200
            assert interval == 600
            assert interval < max_length, "Heartbeat should fire multiple times during crawl"
            expected_heartbeats = max_length // interval
            assert expected_heartbeats >= 5, "Should have reasonable number of heartbeats"


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatWithOtherSettings:
    """Tests heartbeat interval interaction with other crawler settings."""

    async def test_heartbeat_independent_of_retry_settings(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Heartbeat interval is independent of retry configuration.

        Heartbeat is for job-level observability, not request-level retries.
        """
        # Note: crawl_job_max_age_seconds must be <= tenant_worker_semaphore_ttl_seconds - 300
        # Default TTL is 2400, so max_age must be <= 2100
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_heartbeat_interval_seconds": 120,
                "retry_times": 5,
                "crawl_job_max_age_seconds": 1800,  # Must be <= TTL(2400) - 300
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200, f"PUT failed: {response.text}"

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            heartbeat = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )
            retries = get_crawler_setting("retry_times", tenant.crawler_settings)
            max_age = get_crawler_setting(
                "crawl_job_max_age_seconds", tenant.crawler_settings
            )

            # Verify all settings configured independently
            assert heartbeat == 120
            assert retries == 5
            assert max_age == 1800

    async def test_heartbeat_with_stale_threshold(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Heartbeat interval should be shorter than stale threshold.

        If heartbeat > stale threshold, job would be marked stale before heartbeat fires.
        """
        # Configure with reasonable relationship
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_heartbeat_interval_seconds": 300,  # 5 minutes
                "crawl_stale_threshold_minutes": 10,  # 10 minutes
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            heartbeat_seconds = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )
            stale_minutes = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )

            # Verify sensible relationship
            stale_seconds = stale_minutes * 60
            assert heartbeat_seconds < stale_seconds, (
                "Heartbeat should fire before stale threshold to prevent false positives"
            )
