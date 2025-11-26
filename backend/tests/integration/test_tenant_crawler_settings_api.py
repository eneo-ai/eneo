"""Integration tests for tenant crawler settings API endpoints.

Tests the PUT/GET/DELETE endpoints for managing tenant-specific crawler settings.
Requires super_admin_token for authentication (system admin only).
"""

import pytest
from uuid import uuid4


@pytest.fixture
async def super_api_key(test_settings):
    """Get the super admin API key for sysadmin endpoints."""
    return test_settings.intric_super_api_key


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateCrawlerSettings:
    """Tests for PUT /tenants/{tenant_id}/crawler-settings"""

    async def test_update_single_setting(self, client, test_tenant, super_api_key):
        """Partial update changes only specified setting."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 150},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["download_timeout"] == 150
        assert "download_timeout" in data["overrides"]
        # Other settings should remain at defaults
        assert data["settings"]["dns_timeout"] == 30

    async def test_update_multiple_settings(self, client, test_tenant, super_api_key):
        """Multiple settings can be updated in single request."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "download_timeout": 120,
                "dns_timeout": 45,
                "retry_times": 5,
            },
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["download_timeout"] == 120
        assert data["settings"]["dns_timeout"] == 45
        assert data["settings"]["retry_times"] == 5
        assert set(data["overrides"]) >= {"download_timeout", "dns_timeout", "retry_times"}

    async def test_empty_request_returns_current_settings(
        self, client, test_tenant, super_api_key
    ):
        """Empty payload returns current settings without modification."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert len(data["settings"]) == 14

    async def test_validation_rejects_out_of_range_below_min(
        self, client, test_tenant, super_api_key
    ):
        """Pydantic validation rejects values below minimum."""
        # download_timeout must be >= 10
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 5},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 422

    async def test_validation_rejects_out_of_range_above_max(
        self, client, test_tenant, super_api_key
    ):
        """Pydantic validation rejects values above maximum."""
        # download_timeout must be <= 300
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 500},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 422

    async def test_validation_rejects_wrong_type(
        self, client, test_tenant, super_api_key
    ):
        """Pydantic validation rejects wrong types."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": "not_a_number"},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 422

    async def test_nonexistent_tenant_returns_404(self, client, super_api_key):
        """Returns 404 for non-existent tenant."""
        fake_id = uuid4()
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{fake_id}/crawler-settings",
            json={"download_timeout": 100},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 404

    async def test_requires_super_api_key(self, client, test_tenant):
        """Endpoint requires super API key authentication."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 100},
        )
        assert response.status_code in [401, 403]

    async def test_invalid_api_key_rejected(self, client, test_tenant):
        """Invalid API key is rejected."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 100},
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code in [401, 403]

    async def test_update_boolean_settings(self, client, test_tenant, super_api_key):
        """Boolean settings can be updated."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"obey_robots": False, "autothrottle_enabled": False},
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["obey_robots"] is False
        assert data["settings"]["autothrottle_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.integration
class TestGetCrawlerSettings:
    """Tests for GET /tenants/{tenant_id}/crawler-settings"""

    async def test_returns_defaults_for_new_tenant(
        self, client, test_tenant, super_api_key
    ):
        """New tenant gets all defaults with empty overrides."""
        # First reset any existing settings
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )

        response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overrides"] == []
        assert "download_timeout" in data["settings"]
        assert len(data["settings"]) == 14

    async def test_returns_merged_settings_after_update(
        self, client, test_tenant, super_api_key
    ):
        """After update, returns merged tenant + defaults."""
        # First update
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 180},
            headers={"X-API-Key": super_api_key},
        )
        # Then get
        response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["download_timeout"] == 180
        assert "download_timeout" in data["overrides"]

    async def test_nonexistent_tenant_returns_404(self, client, super_api_key):
        """Returns 404 for non-existent tenant."""
        fake_id = uuid4()
        response = await client.get(
            f"/api/v1/sysadmin/tenants/{fake_id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 404

    async def test_requires_super_api_key(self, client, test_tenant):
        """Endpoint requires super API key authentication."""
        response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
        )
        assert response.status_code in [401, 403]


@pytest.mark.asyncio
@pytest.mark.integration
class TestDeleteCrawlerSettings:
    """Tests for DELETE /tenants/{tenant_id}/crawler-settings"""

    async def test_reset_removes_all_overrides(
        self, client, test_tenant, super_api_key
    ):
        """DELETE resets to defaults."""
        # First set some overrides
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 200, "dns_timeout": 60},
            headers={"X-API-Key": super_api_key},
        )
        # Then delete
        response = await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        data = response.json()
        assert "download_timeout" in data["deleted_keys"]
        assert "dns_timeout" in data["deleted_keys"]

        # Verify settings are back to defaults
        get_response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert get_response.json()["overrides"] == []

    async def test_delete_idempotent(self, client, test_tenant, super_api_key):
        """DELETE on tenant with no overrides is safe."""
        # First ensure no overrides exist
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        # Delete again
        response = await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 200
        assert response.json()["deleted_keys"] == []

    async def test_nonexistent_tenant_returns_404(self, client, super_api_key):
        """Returns 404 for non-existent tenant."""
        fake_id = uuid4()
        response = await client.delete(
            f"/api/v1/sysadmin/tenants/{fake_id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert response.status_code == 404

    async def test_requires_super_api_key(self, client, test_tenant):
        """Endpoint requires super API key authentication."""
        response = await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
        )
        assert response.status_code in [401, 403]


@pytest.mark.asyncio
@pytest.mark.integration
class TestCrawlerSettingsWorkflow:
    """End-to-end workflow tests for crawler settings."""

    async def test_full_crud_workflow(self, client, test_tenant, super_api_key):
        """Complete create-read-update-delete workflow."""
        # 1. Reset to defaults
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )

        # 2. Verify defaults
        get_response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["overrides"] == []
        default_timeout = data["settings"]["download_timeout"]

        # 3. Update settings
        update_response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 250},
            headers={"X-API-Key": super_api_key},
        )
        assert update_response.status_code == 200
        assert update_response.json()["settings"]["download_timeout"] == 250

        # 4. Verify update persisted
        get_response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert get_response.json()["settings"]["download_timeout"] == 250

        # 5. Delete (reset)
        delete_response = await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert delete_response.status_code == 200

        # 6. Verify back to defaults
        get_response = await client.get(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )
        assert get_response.json()["settings"]["download_timeout"] == default_timeout
        assert get_response.json()["overrides"] == []

    async def test_partial_updates_accumulate(self, client, test_tenant, super_api_key):
        """Multiple partial updates accumulate correctly."""
        # Reset first
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_api_key},
        )

        # Update 1: set download_timeout
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"download_timeout": 100},
            headers={"X-API-Key": super_api_key},
        )

        # Update 2: set dns_timeout (should not affect download_timeout)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"dns_timeout": 50},
            headers={"X-API-Key": super_api_key},
        )

        data = response.json()
        assert data["settings"]["download_timeout"] == 100
        assert data["settings"]["dns_timeout"] == 50
        assert set(data["overrides"]) >= {"download_timeout", "dns_timeout"}
