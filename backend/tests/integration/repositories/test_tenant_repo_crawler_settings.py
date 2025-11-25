"""Integration tests for TenantRepository crawler_settings JSONB operations.

Tests PostgreSQL JSONB atomic merge operations for crawler settings:
- update_crawler_settings: Uses PostgreSQL || operator for atomic merge
- clear_crawler_settings: Resets to empty JSONB
- Race condition prevention via atomic operations
"""

import pytest
import asyncio


@pytest.mark.asyncio
@pytest.mark.integration
class TestUpdateCrawlerSettings:
    """Tests for atomic JSONB merge operations."""

    async def test_update_creates_new_settings(self, db_container, test_tenant):
        """First update creates crawler_settings JSONB."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            updated = await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"download_timeout": 120},
            )

            assert updated.crawler_settings["download_timeout"] == 120

    async def test_update_merges_not_replaces(self, db_container, test_tenant):
        """CRITICAL: Update merges with existing, doesn't replace."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First update
            await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"download_timeout": 120},
            )

            # Second update with different key
            updated = await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"dns_timeout": 60},
            )

            # Both should exist (merge, not replace)
            assert updated.crawler_settings["download_timeout"] == 120
            assert updated.crawler_settings["dns_timeout"] == 60

    async def test_update_overwrites_existing_key(self, db_container, test_tenant):
        """Updating same key overwrites the value."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First update
            await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"download_timeout": 100},
            )

            # Update same key with different value
            updated = await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"download_timeout": 200},
            )

            assert updated.crawler_settings["download_timeout"] == 200

    async def test_update_multiple_keys_at_once(self, db_container, test_tenant):
        """Multiple keys can be updated in single operation."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            updated = await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={
                    "download_timeout": 150,
                    "dns_timeout": 45,
                    "retry_times": 5,
                },
            )

            assert updated.crawler_settings["download_timeout"] == 150
            assert updated.crawler_settings["dns_timeout"] == 45
            assert updated.crawler_settings["retry_times"] == 5


@pytest.mark.asyncio
@pytest.mark.integration
class TestAtomicJSONBMerge:
    """Tests for race condition prevention via atomic JSONB merge."""

    async def test_concurrent_updates_no_lost_writes(self, db_container, test_tenant):
        """RACE CONDITION TEST: Concurrent updates don't lose data.

        This test verifies that the PostgreSQL || operator prevents
        lost updates when multiple concurrent requests modify different keys.
        """
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Clear any existing settings first
            await tenant_repo.clear_crawler_settings(tenant_id=test_tenant.id)

            # Simulate concurrent updates from different workers
            async def update_setting(key: str, value: int):
                await tenant_repo.update_crawler_settings(
                    tenant_id=test_tenant.id,
                    crawler_settings={key: value},
                )

            # Run 5 concurrent updates with different keys
            await asyncio.gather(
                update_setting("download_timeout", 100),
                update_setting("dns_timeout", 50),
                update_setting("retry_times", 5),
                update_setting("crawl_max_length", 7200),
                update_setting("crawl_feeder_batch_size", 20),
            )

            # Verify ALL writes persisted (no lost updates)
            tenant = await tenant_repo.get(test_tenant.id)
            assert tenant.crawler_settings.get("download_timeout") == 100
            assert tenant.crawler_settings.get("dns_timeout") == 50
            assert tenant.crawler_settings.get("retry_times") == 5
            assert tenant.crawler_settings.get("crawl_max_length") == 7200
            assert tenant.crawler_settings.get("crawl_feeder_batch_size") == 20

    async def test_concurrent_updates_same_key_last_write_wins(
        self, db_container, test_tenant
    ):
        """Concurrent updates to same key: last write wins."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            await tenant_repo.clear_crawler_settings(tenant_id=test_tenant.id)

            # Multiple updates to same key
            async def update_timeout(value: int):
                await tenant_repo.update_crawler_settings(
                    tenant_id=test_tenant.id,
                    crawler_settings={"download_timeout": value},
                )

            # Run concurrent updates
            await asyncio.gather(
                update_timeout(100),
                update_timeout(200),
                update_timeout(150),
            )

            # One of the values should persist (last write wins)
            tenant = await tenant_repo.get(test_tenant.id)
            assert tenant.crawler_settings.get("download_timeout") in [100, 200, 150]


@pytest.mark.asyncio
@pytest.mark.integration
class TestClearCrawlerSettings:
    """Tests for clear_crawler_settings operation."""

    async def test_clear_removes_all_settings(self, db_container, test_tenant):
        """clear_crawler_settings removes all overrides."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Set some settings
            await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"download_timeout": 120, "dns_timeout": 60},
            )

            # Verify settings exist
            tenant = await tenant_repo.get(test_tenant.id)
            assert len(tenant.crawler_settings) >= 2

            # Clear
            await tenant_repo.clear_crawler_settings(tenant_id=test_tenant.id)

            # Verify empty
            tenant = await tenant_repo.get(test_tenant.id)
            assert tenant.crawler_settings == {}

    async def test_clear_idempotent(self, db_container, test_tenant):
        """Clearing already empty settings is safe."""
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Clear first time
            await tenant_repo.clear_crawler_settings(tenant_id=test_tenant.id)

            # Clear second time (should not error)
            await tenant_repo.clear_crawler_settings(tenant_id=test_tenant.id)

            tenant = await tenant_repo.get(test_tenant.id)
            assert tenant.crawler_settings == {}


@pytest.mark.asyncio
@pytest.mark.integration
class TestCrawlerSettingsIntegrationWithHelper:
    """Tests verifying consumers correctly use tenant-specific settings."""

    async def test_tenant_settings_used_by_helper(self, db_container, test_tenant):
        """get_crawler_setting() correctly uses tenant overrides from DB."""
        from intric.tenants.crawler_settings_helper import get_crawler_setting

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Set tenant-specific limit
            await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"tenant_worker_concurrency_limit": 2},
            )

            # Retrieve and verify via helper
            tenant = await tenant_repo.get(test_tenant.id)
            limit = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant.crawler_settings,
                default=4,
            )
            assert limit == 2

    async def test_feeder_batch_size_from_db(self, db_container, test_tenant):
        """Feeder batch size correctly retrieved from tenant settings."""
        from intric.tenants.crawler_settings_helper import get_crawler_setting

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"crawl_feeder_batch_size": 5},
            )

            tenant = await tenant_repo.get(test_tenant.id)
            batch_size = get_crawler_setting(
                "crawl_feeder_batch_size",
                tenant.crawler_settings,
                default=10,
            )
            assert batch_size == 5

    async def test_get_all_settings_merges_correctly(self, db_container, test_tenant):
        """get_all_crawler_settings() merges tenant overrides with defaults."""
        from intric.tenants.crawler_settings_helper import get_all_crawler_settings

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            await tenant_repo.update_crawler_settings(
                tenant_id=test_tenant.id,
                crawler_settings={"download_timeout": 175, "obey_robots": False},
            )

            tenant = await tenant_repo.get(test_tenant.id)
            all_settings = get_all_crawler_settings(tenant.crawler_settings)

            # Verify overrides
            assert all_settings["download_timeout"] == 175
            assert all_settings["obey_robots"] is False

            # Verify defaults still present
            assert "dns_timeout" in all_settings
            assert "crawl_max_length" in all_settings
            assert len(all_settings) == 14
