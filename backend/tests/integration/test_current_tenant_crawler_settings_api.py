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
            },
            headers={"X-API-Key": admin_user_api_key.key},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["crawl_sitemap_lastmod_skip_enabled"] is True
        assert data["settings"]["obey_robots"] is True
        assert data["settings"]["autothrottle_enabled"] is False
        assert set(data["overrides"]) >= {
            "crawl_sitemap_lastmod_skip_enabled",
            "obey_robots",
            "autothrottle_enabled",
        }

    async def test_admin_cannot_update_operator_only_crawler_settings(
        self, client, admin_user_api_key
    ):
        response = await client.patch(
            "/api/v1/settings/crawler",
            json={
                "crawl_sitemap_lastmod_skip_enabled": True,
                "download_timeout": 120,
            },
            headers={"X-API-Key": admin_user_api_key.key},
        )

        assert response.status_code == 422
