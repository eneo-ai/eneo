import pytest


@pytest.mark.asyncio
@pytest.mark.integration
class TestCurrentTenantCrawlerSettings:
    async def test_admin_can_read_effective_crawler_settings(
        self, client, admin_user_api_key
    ):
        response = await client.get(
            "/api/v1/settings/crawler",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["crawl_sitemap_lastmod_skip_enabled"] is False
        assert data["settings"]["obey_robots"] in [True, False]
        assert "download_timeout" in data["settings"]
        assert "crawl_http_cache_enabled" not in data["settings"]

    async def test_admin_can_update_self_service_crawler_settings(
        self, client, admin_user_api_key
    ):
        response = await client.patch(
            "/api/v1/settings/crawler",
            json={
                "crawl_sitemap_lastmod_skip_enabled": True,
                "obey_robots": True,
                "autothrottle_enabled": False,
                "download_max_size": 52_428_800,
                "download_timeout": 120,
                "dns_timeout": 45,
                "retry_times": 3,
                "closespider_itemcount": 5_000,
            },
            headers={"X-API-Key": admin_user_api_key.key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["crawl_sitemap_lastmod_skip_enabled"] is True
        assert data["settings"]["obey_robots"] is True
        assert data["settings"]["autothrottle_enabled"] is False
        assert data["settings"]["download_max_size"] == 52_428_800
        assert data["settings"]["download_timeout"] == 120
        assert data["settings"]["dns_timeout"] == 45
        assert data["settings"]["retry_times"] == 3
        assert data["settings"]["closespider_itemcount"] == 5_000
        assert set(data["overrides"]) >= {
            "crawl_sitemap_lastmod_skip_enabled",
            "obey_robots",
            "autothrottle_enabled",
            "download_max_size",
            "download_timeout",
            "dns_timeout",
            "retry_times",
            "closespider_itemcount",
        }
        assert set(data["editable_settings"]) >= {
            "download_max_size",
            "download_timeout",
            "dns_timeout",
            "retry_times",
            "closespider_itemcount",
        }
        assert data["specs"]["download_max_size"]["min"] == 1_048_576
        assert data["specs"]["download_max_size"]["max"] == 1_073_741_824

    async def test_admin_cannot_update_operator_only_crawler_settings(
        self, client, admin_user_api_key
    ):
        # Capacity governance and global feeder knobs stay sysadmin-only;
        # crawl_page_batch_size is deferred to the token-efficiency tranche.
        for operator_payload in [
            {"tenant_worker_concurrency_limit": 10},
            {"crawl_page_batch_size": 200},
            {"tenant_worker_semaphore_ttl_seconds": 7200},
            {"crawl_feeder_enabled": False},
            {"crawl_feeder_interval_seconds": 30},
            {"crawl_feeder_batch_size": 50},
        ]:
            response = await client.patch(
                "/api/v1/settings/crawler",
                json=operator_payload,
                headers={"X-API-Key": admin_user_api_key.key},
            )

            assert response.status_code == 422

    async def test_admin_can_update_tenant_runtime_knobs(
        self, client, admin_user_api_key
    ):
        """Sub-tranche 3a expansion: tenant-scoped runtime knobs that
        affect this tenant's crawls only (read at crawl start, no impact
        on already-running crawls) are now tenant-admin editable.

        Bounds come from the canonical CrawlerSettingSpec so the API
        boundary and the worker runtime stay in sync.
        """
        response = await client.patch(
            "/api/v1/settings/crawler",
            json={
                "crawl_max_length": 7200,
                "crawl_stale_threshold_minutes": 30,
                "queued_stale_threshold_minutes": 10,
                "crawl_heartbeat_interval_seconds": 300,
                "crawl_job_max_age_seconds": 3600,
            },
            headers={"X-API-Key": admin_user_api_key.key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["crawl_max_length"] == 7200
        assert data["settings"]["crawl_stale_threshold_minutes"] == 30
        assert data["settings"]["queued_stale_threshold_minutes"] == 10
        assert data["settings"]["crawl_heartbeat_interval_seconds"] == 300
        assert data["settings"]["crawl_job_max_age_seconds"] == 3600
        assert set(data["overrides"]) >= {
            "crawl_max_length",
            "crawl_stale_threshold_minutes",
            "queued_stale_threshold_minutes",
            "crawl_heartbeat_interval_seconds",
            "crawl_job_max_age_seconds",
        }
        assert set(data["editable_settings"]) >= {
            "crawl_max_length",
            "crawl_stale_threshold_minutes",
            "queued_stale_threshold_minutes",
            "crawl_heartbeat_interval_seconds",
            "crawl_job_max_age_seconds",
        }
        # Validation bounds surface in the specs map so the admin UI can
        # render min/max hints without hardcoding them.
        assert data["specs"]["crawl_max_length"]["min"] == 60
        assert data["specs"]["crawl_max_length"]["max"] == 86400

    async def test_admin_runtime_knob_update_rejects_out_of_bounds(
        self, client, admin_user_api_key
    ):
        """The Pydantic field bounds reject out-of-range values at the API
        boundary; the worker never sees an unsafe value."""
        response = await client.patch(
            "/api/v1/settings/crawler",
            json={"crawl_max_length": 30},  # below the 60s minimum
            headers={"X-API-Key": admin_user_api_key.key},
        )
        assert response.status_code == 422
