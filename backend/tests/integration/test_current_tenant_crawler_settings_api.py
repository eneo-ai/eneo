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
        for operator_payload in [
            {"tenant_worker_concurrency_limit": 10},
            {"crawl_page_batch_size": 200},
            {"crawl_max_length": 7200},
        ]:
            response = await client.patch(
                "/api/v1/settings/crawler",
                json=operator_payload,
                headers={"X-API-Key": admin_user_api_key.key},
            )

            assert response.status_code == 422
