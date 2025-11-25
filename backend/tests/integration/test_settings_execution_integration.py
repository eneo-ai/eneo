"""Integration tests for crawler settings execution and propagation.

Tests the end-to-end flow of crawler settings from API storage through to worker retrieval:
- Settings stored via API endpoint reach the database correctly
- Helper functions retrieve correct merged settings (tenant + defaults)
- Settings changes apply immediately without restart
- Multi-tenant isolation prevents setting leakage
- Worker components can access tenant-specific settings

This verifies the CRITICAL gap: that settings don't just store correctly,
but actually propagate through all layers to affect worker behavior.
"""

import pytest
from uuid import uuid4
from httpx import AsyncClient

from intric.tenants.crawler_settings_helper import (
    get_crawler_setting,
    get_all_crawler_settings,
    CRAWLER_SETTING_SPECS,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestSettingsPropagation:
    """Tests that settings flow correctly from API → Database → Helper functions."""

    async def test_api_setting_propagates_to_helper_retrieval(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """CRITICAL: Settings stored via API are retrievable by helper functions.

        This is the core integration test ensuring settings actually work in production.
        If this fails, settings are stored but never used by workers.
        """
        # 1. Store setting via API
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 150, "retry_times": 5},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # 2. Retrieve tenant from database (simulating what worker does)
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # 3. Verify helper functions return the custom values
            timeout = get_crawler_setting(
                "download_timeout",
                tenant.crawler_settings,
            )
            retries = get_crawler_setting(
                "retry_times",
                tenant.crawler_settings,
            )

            assert timeout == 150, "Helper should return tenant override, not default"
            assert retries == 5, "Helper should return tenant override, not default"

    async def test_unset_settings_return_defaults(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Settings not explicitly set should return environment/hardcoded defaults."""
        # Reset all settings to defaults
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # Should return hardcoded default (90) from CRAWLER_SETTING_SPECS
            timeout = get_crawler_setting(
                "download_timeout",
                tenant.crawler_settings,
            )
            assert timeout == 90, "Should return hardcoded default when no override"

            # Should return hardcoded default (2) from CRAWLER_SETTING_SPECS
            retries = get_crawler_setting(
                "retry_times",
                tenant.crawler_settings,
            )
            assert retries == 2, "Should return hardcoded default when no override"

    async def test_get_all_settings_merges_correctly(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """get_all_crawler_settings returns complete merged settings dict."""
        # Set partial overrides
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "download_timeout": 200,
                "dns_timeout": 60,
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # Get all settings (should merge tenant + defaults)
            all_settings = get_all_crawler_settings(tenant.crawler_settings)

            # Verify overrides present
            assert all_settings["download_timeout"] == 200
            assert all_settings["dns_timeout"] == 60

            # Verify defaults present for non-overridden settings
            assert all_settings["retry_times"] == 2  # Hardcoded default
            assert "crawl_max_length" in all_settings
            assert "tenant_worker_concurrency_limit" in all_settings

            # Should have ALL settings from CRAWLER_SETTING_SPECS
            assert len(all_settings) == len(CRAWLER_SETTING_SPECS)


@pytest.mark.asyncio
@pytest.mark.integration
class TestSettingsImmediateApplication:
    """Tests that settings changes apply immediately without restart."""

    async def test_settings_change_visible_immediately(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Settings changes should be visible on next database read.

        This ensures workers don't need restart to pick up new settings.
        """
        # Initial setting
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 100},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First read
            tenant = await tenant_repo.get(test_tenant.id)
            timeout_1 = get_crawler_setting("download_timeout", tenant.crawler_settings)
            assert timeout_1 == 100

            # Update setting
            await client.put(
                f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
                json={"download_timeout": 250},
                headers={"X-API-Key": super_admin_token},
            )

            # Second read (simulating next job execution)
            tenant = await tenant_repo.get(test_tenant.id)
            timeout_2 = get_crawler_setting("download_timeout", tenant.crawler_settings)
            assert timeout_2 == 250, "Setting change should be visible immediately"

    async def test_partial_update_preserves_other_settings(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Updating one setting shouldn't affect others (JSONB merge, not replace)."""
        # Set multiple settings
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "download_timeout": 120,
                "dns_timeout": 45,
                "retry_times": 7,
            },
            headers={"X-API-Key": super_admin_token},
        )

        # Update only download_timeout
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 180},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)
            all_settings = get_all_crawler_settings(tenant.crawler_settings)

            # Updated setting should have new value
            assert all_settings["download_timeout"] == 180

            # Other settings should remain unchanged
            assert all_settings["dns_timeout"] == 45, "dns_timeout should be preserved"
            assert all_settings["retry_times"] == 7, "retry_times should be preserved"


@pytest.mark.asyncio
@pytest.mark.integration
class TestMultiTenantSettingsIsolation:
    """Tests that tenant settings don't leak between tenants."""

    async def test_tenant_settings_isolated(
        self, client: AsyncClient, super_admin_token, db_container
    ):
        """Each tenant's settings should be completely isolated.

        CRITICAL: Settings leakage would allow one tenant to affect another's crawl behavior.
        """
        # Create two test tenants
        tenant_1_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-isolation-1-{uuid4().hex[:6]}",
                "display_name": "Tenant 1",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_1_response.status_code == 200
        tenant_1_id = tenant_1_response.json()["id"]

        tenant_2_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-isolation-2-{uuid4().hex[:6]}",
                "display_name": "Tenant 2",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_2_response.status_code == 200
        tenant_2_id = tenant_2_response.json()["id"]

        # Set different settings for each tenant
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_1_id}/crawler-settings",
            json={"download_timeout": 100, "retry_times": 3},
            headers={"X-API-Key": super_admin_token},
        )

        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_2_id}/crawler-settings",
            json={"download_timeout": 250, "retry_times": 8},
            headers={"X-API-Key": super_admin_token},
        )

        # Verify isolation
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Get tenants by ID (repository only has get() method)
            tenant_1 = await tenant_repo.get(tenant_1_id)
            tenant_2 = await tenant_repo.get(tenant_2_id)

            # Tenant 1 settings
            t1_timeout = get_crawler_setting("download_timeout", tenant_1.crawler_settings)
            t1_retries = get_crawler_setting("retry_times", tenant_1.crawler_settings)

            # Tenant 2 settings
            t2_timeout = get_crawler_setting("download_timeout", tenant_2.crawler_settings)
            t2_retries = get_crawler_setting("retry_times", tenant_2.crawler_settings)

            # Verify complete isolation
            assert t1_timeout == 100, "Tenant 1 should have its own timeout"
            assert t2_timeout == 250, "Tenant 2 should have its own timeout"
            assert t1_retries == 3, "Tenant 1 should have its own retry count"
            assert t2_retries == 8, "Tenant 2 should have its own retry count"


@pytest.mark.asyncio
@pytest.mark.integration
class TestBooleanAndRangeSettings:
    """Tests for boolean settings and range validation."""

    async def test_boolean_settings_propagate(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Boolean settings (obey_robots, autothrottle_enabled) work correctly."""
        # Set boolean settings
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "obey_robots": False,
                "autothrottle_enabled": False,
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            obey_robots = get_crawler_setting("obey_robots", tenant.crawler_settings)
            autothrottle = get_crawler_setting("autothrottle_enabled", tenant.crawler_settings)

            assert obey_robots is False
            assert autothrottle is False

    async def test_concurrency_limit_setting_propagates(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """tenant_worker_concurrency_limit setting affects worker behavior.

        This setting controls how many concurrent jobs a tenant can run.
        """
        # Set custom concurrency limit
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"tenant_worker_concurrency_limit": 3},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant.crawler_settings,
            )
            assert limit == 3, "Custom concurrency limit should propagate"

    async def test_feeder_batch_size_setting_propagates(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_feeder_batch_size setting controls feeder enqueueing.

        This setting controls how many jobs the feeder enqueues per cycle.
        """
        # Set custom batch size
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_feeder_batch_size": 5},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            batch_size = get_crawler_setting(
                "crawl_feeder_batch_size",
                tenant.crawler_settings,
            )
            assert batch_size == 5, "Custom batch size should propagate"


@pytest.mark.asyncio
@pytest.mark.integration
class TestHeartbeatAndTimeoutSettings:
    """Tests for new heartbeat and timeout settings added in this branch."""

    async def test_heartbeat_interval_setting_propagates(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_heartbeat_interval_seconds setting for observability."""
        # Set custom heartbeat interval
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_heartbeat_interval_seconds": 600},  # 10 minutes
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            interval = get_crawler_setting(
                "crawl_heartbeat_interval_seconds",
                tenant.crawler_settings,
            )
            assert interval == 600, "Custom heartbeat interval should propagate"

    async def test_stale_threshold_setting_propagates(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_stale_threshold_minutes setting for stale job detection."""
        # Set custom stale threshold
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 15},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes",
                tenant.crawler_settings,
            )
            assert threshold == 15, "Custom stale threshold should propagate"

    async def test_job_max_age_setting_propagates(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_job_max_age_seconds setting for retry age limits."""
        # Set custom max age
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_job_max_age_seconds": 1800},  # 30 minutes
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            max_age = get_crawler_setting(
                "crawl_job_max_age_seconds",
                tenant.crawler_settings,
            )
            assert max_age == 1800, "Custom max age should propagate"
