"""Integration tests for crawler timeout settings enforcement.

Tests that timeout settings (download_timeout, dns_timeout, crawl_max_length)
are correctly configured and ready for enforcement by the crawler:
- Settings flow from API through database to worker code
- Worker retrieves correct timeout values for each tenant
- Timeout values are within valid ranges and properly typed
- Multi-tenant timeout isolation

Note: Full E2E testing of actual HTTP timeout enforcement would require
running live Scrapy crawlers with test HTTP servers that delay responses.
These tests verify the integration layer that makes timeout enforcement possible.
"""

import pytest
from httpx import AsyncClient

from intric.tenants.crawler_settings_helper import (
    get_crawler_setting,
    CRAWLER_SETTING_SPECS,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestTimeoutConfiguration:
    """Tests that timeout settings are correctly configured for worker use."""

    async def test_download_timeout_configured_correctly(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """download_timeout setting flows from API to worker retrieval.

        This is the critical path for timeout enforcement:
        1. Admin sets timeout via API
        2. Worker retrieves timeout from database
        3. Worker uses timeout for HTTP requests
        """
        # Set custom download timeout
        timeout_value = 120  # 2 minutes
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": timeout_value},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Verify worker can retrieve it (simulating worker startup)
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # This is exactly how crawl_tasks.py retrieves the setting
            configured_timeout = get_crawler_setting(
                "download_timeout",
                tenant.crawler_settings,
            )

            assert configured_timeout == timeout_value
            assert isinstance(configured_timeout, int)
            assert 10 <= configured_timeout <= 300, "Timeout must be in valid range"

    async def test_dns_timeout_configured_correctly(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """dns_timeout setting flows from API to worker retrieval."""
        # Set custom DNS timeout
        timeout_value = 15  # 15 seconds
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"dns_timeout": timeout_value},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Verify worker can retrieve it
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            configured_timeout = get_crawler_setting(
                "dns_timeout",
                tenant.crawler_settings,
            )

            assert configured_timeout == timeout_value
            assert isinstance(configured_timeout, int)
            assert 5 <= configured_timeout <= 120, "DNS timeout must be in valid range"

    async def test_crawl_max_length_configured_correctly(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_max_length setting flows from API to worker retrieval.

        This setting controls maximum crawl duration before automatic termination.
        """
        # Set custom crawl max length
        max_length = 1800  # 30 minutes
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_max_length": max_length},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Verify worker can retrieve it
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            configured_max_length = get_crawler_setting(
                "crawl_max_length",
                tenant.crawler_settings,
            )

            assert configured_max_length == max_length
            assert isinstance(configured_max_length, int)
            assert 60 <= configured_max_length <= 86400, "Max length must be in valid range"


@pytest.mark.asyncio
@pytest.mark.integration
class TestTimeoutRangeValidation:
    """Tests that timeout settings enforce their min/max ranges."""

    async def test_download_timeout_rejects_below_minimum(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """download_timeout must be >= 10 seconds."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 5},  # Below minimum
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject timeout below 10s"

    async def test_download_timeout_rejects_above_maximum(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """download_timeout must be <= 300 seconds (5 minutes)."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 500},  # Above maximum
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject timeout above 300s"

    async def test_download_timeout_accepts_valid_range(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """download_timeout accepts values within valid range."""
        # Test minimum boundary
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 10},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test maximum boundary
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 300},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test middle value
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 150},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

    async def test_dns_timeout_range_validation(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """dns_timeout must be within 5-120 seconds."""
        # Below minimum
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"dns_timeout": 2},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422

        # Above maximum
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"dns_timeout": 150},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422

        # Valid range
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"dns_timeout": 30},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

    async def test_crawl_max_length_range_validation(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """crawl_max_length must be within 60-86400 seconds (1 min to 24 hours)."""
        # Below minimum
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_max_length": 30},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422

        # Above maximum
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_max_length": 100000},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422

        # Valid range
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_max_length": 3600},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
class TestTimeoutDefaultBehavior:
    """Tests timeout default values when not explicitly configured."""

    async def test_download_timeout_defaults_correctly(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """When not set, download_timeout should return hardcoded default (90s)."""
        # Reset settings to defaults
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # Should return hardcoded default from CRAWLER_SETTING_SPECS
            default_timeout = get_crawler_setting(
                "download_timeout",
                tenant.crawler_settings,
            )

            expected_default = CRAWLER_SETTING_SPECS["download_timeout"]["default"]
            assert default_timeout == expected_default
            assert default_timeout == 90, "Hardcoded default should be 90s"

    async def test_dns_timeout_defaults_correctly(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """When not set, dns_timeout should return hardcoded default (30s)."""
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            default_timeout = get_crawler_setting(
                "dns_timeout",
                tenant.crawler_settings,
            )

            expected_default = CRAWLER_SETTING_SPECS["dns_timeout"]["default"]
            assert default_timeout == expected_default
            assert default_timeout == 30, "Hardcoded default should be 30s"


@pytest.mark.asyncio
@pytest.mark.integration
class TestMultiTenantTimeoutIsolation:
    """Tests that timeout settings are isolated between tenants."""

    async def test_different_tenants_different_timeouts(
        self, client: AsyncClient, super_admin_token, db_container
    ):
        """Each tenant can have completely independent timeout configurations.

        CRITICAL: Timeout leakage would cause one tenant's crawls to use
        another tenant's timeout settings.
        """
        from uuid import uuid4

        # Create two test tenants
        tenant_1_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-timeout-1-{uuid4().hex[:6]}",
                "display_name": "Fast Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_1_response.status_code == 200
        tenant_1 = tenant_1_response.json()

        tenant_2_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-timeout-2-{uuid4().hex[:6]}",
                "display_name": "Slow Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_2_response.status_code == 200
        tenant_2 = tenant_2_response.json()

        # Configure fast timeouts for tenant 1
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_1['id']}/crawler-settings",
            json={
                "download_timeout": 30,  # Fast timeout
                "dns_timeout": 10,
                "crawl_max_length": 300,  # 5 minutes
            },
            headers={"X-API-Key": super_admin_token},
        )

        # Configure slow timeouts for tenant 2
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_2['id']}/crawler-settings",
            json={
                "download_timeout": 200,  # Slow timeout
                "dns_timeout": 90,
                "crawl_max_length": 7200,  # 2 hours
            },
            headers={"X-API-Key": super_admin_token},
        )

        # Verify isolation
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Get tenant 1
            t1 = await tenant_repo.get(tenant_1["id"])
            t1_download = get_crawler_setting("download_timeout", t1.crawler_settings)
            t1_dns = get_crawler_setting("dns_timeout", t1.crawler_settings)
            t1_max_length = get_crawler_setting("crawl_max_length", t1.crawler_settings)

            # Get tenant 2
            t2 = await tenant_repo.get(tenant_2["id"])
            t2_download = get_crawler_setting("download_timeout", t2.crawler_settings)
            t2_dns = get_crawler_setting("dns_timeout", t2.crawler_settings)
            t2_max_length = get_crawler_setting("crawl_max_length", t2.crawler_settings)

            # Verify complete isolation
            assert t1_download == 30, "Tenant 1 should have fast download timeout"
            assert t2_download == 200, "Tenant 2 should have slow download timeout"

            assert t1_dns == 10, "Tenant 1 should have fast DNS timeout"
            assert t2_dns == 90, "Tenant 2 should have slow DNS timeout"

            assert t1_max_length == 300, "Tenant 1 should have short max length"
            assert t2_max_length == 7200, "Tenant 2 should have long max length"


@pytest.mark.asyncio
@pytest.mark.integration
class TestTimeoutUpdatePropagation:
    """Tests that timeout changes propagate immediately."""

    async def test_timeout_change_visible_on_next_read(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Timeout changes should be visible immediately without restart.

        This ensures workers pick up new timeout values on next job execution.
        """
        # Initial timeout
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 60},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First read
            tenant = await tenant_repo.get(test_tenant.id)
            timeout_1 = get_crawler_setting("download_timeout", tenant.crawler_settings)
            assert timeout_1 == 60

            # Update timeout
            await client.put(
                f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
                json={"download_timeout": 180},
                headers={"X-API-Key": super_admin_token},
            )

            # Second read (simulating next job execution)
            tenant = await tenant_repo.get(test_tenant.id)
            timeout_2 = get_crawler_setting("download_timeout", tenant.crawler_settings)
            assert timeout_2 == 180, "Updated timeout should be visible immediately"

    async def test_all_timeouts_update_independently(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Each timeout setting can be updated independently.

        Updating one timeout shouldn't affect others.
        """
        # Set all timeouts
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "download_timeout": 100,
                "dns_timeout": 20,
                "crawl_max_length": 1800,
            },
            headers={"X-API-Key": super_admin_token},
        )

        # Update only download_timeout
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 250},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # Verify only download_timeout changed
            download = get_crawler_setting("download_timeout", tenant.crawler_settings)
            dns = get_crawler_setting("dns_timeout", tenant.crawler_settings)
            max_length = get_crawler_setting("crawl_max_length", tenant.crawler_settings)

            assert download == 250, "download_timeout should be updated"
            assert dns == 20, "dns_timeout should remain unchanged"
            assert max_length == 1800, "crawl_max_length should remain unchanged"
