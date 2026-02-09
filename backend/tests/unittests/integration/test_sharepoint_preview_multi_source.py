from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intric.integration.infrastructure.preview_service.sharepoint_preview_service import (
    SharePointPreviewService,
)


def _make_site(site_id: str, name: str = "Site") -> dict:
    return {"id": site_id, "displayName": name, "webUrl": f"https://example.com/{site_id}"}


def _make_service(*, is_service_account: bool = False):
    """Create a SharePointPreviewService with mocked dependencies."""
    oauth_token_service = MagicMock()
    tenant_app_auth_service = AsyncMock()
    service_account_auth_service = AsyncMock()
    tenant_sharepoint_app_repo = AsyncMock()

    service = SharePointPreviewService(
        oauth_token_service=oauth_token_service,
        tenant_app_auth_service=tenant_app_auth_service,
        service_account_auth_service=service_account_auth_service,
        tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
    )

    return service


def _make_tenant_app(*, is_service_account: bool = False):
    app = MagicMock()
    app.is_service_account.return_value = is_service_account
    app.auth_method = "service_account" if is_service_account else "tenant_app"
    app.service_account_refresh_token = "old-refresh"
    app.id = "app-id"
    return app


@pytest.mark.asyncio
async def test_fetch_all_accessible_sites_combines_three_sources():
    service = _make_service()
    content_client = AsyncMock()

    content_client.get_sites.return_value = {"value": [_make_site("site-1", "Search Site")]}
    content_client.get_followed_sites.return_value = [_make_site("site-2", "Followed Site")]
    content_client.get_group_connected_sites.return_value = [_make_site("site-3", "Group Site")]

    result = await service._fetch_all_accessible_sites(content_client)

    assert len(result) == 3
    names = {s.name for s in result}
    assert names == {"Search Site", "Followed Site", "Group Site"}


@pytest.mark.asyncio
async def test_fetch_all_accessible_sites_deduplicates_on_id():
    service = _make_service()
    content_client = AsyncMock()

    # Same site ID from all three sources
    content_client.get_sites.return_value = {"value": [_make_site("site-1", "From Search")]}
    content_client.get_followed_sites.return_value = [_make_site("site-1", "From Followed")]
    content_client.get_group_connected_sites.return_value = [_make_site("site-1", "From Group")]

    result = await service._fetch_all_accessible_sites(content_client)

    assert len(result) == 1
    # First occurrence (from search) wins
    assert result[0].name == "From Search"
    assert result[0].key == "site-1"


@pytest.mark.asyncio
async def test_fetch_all_accessible_sites_handles_single_source_failure():
    service = _make_service()
    content_client = AsyncMock()

    content_client.get_sites.return_value = {"value": [_make_site("site-1")]}
    content_client.get_followed_sites.side_effect = Exception("403 Forbidden")
    content_client.get_group_connected_sites.return_value = [_make_site("site-2")]

    result = await service._fetch_all_accessible_sites(content_client)

    assert len(result) == 2
    ids = {s.key for s in result}
    assert ids == {"site-1", "site-2"}


@pytest.mark.asyncio
async def test_fetch_all_accessible_sites_handles_all_sources_failing():
    service = _make_service()
    content_client = AsyncMock()

    content_client.get_sites.side_effect = Exception("Network error")
    content_client.get_followed_sites.side_effect = Exception("Network error")
    content_client.get_group_connected_sites.side_effect = Exception("Network error")

    result = await service._fetch_all_accessible_sites(content_client)

    assert result == []


@pytest.mark.asyncio
async def test_service_account_uses_multi_source():
    """Service account preview should use _fetch_all_accessible_sites."""
    service = _make_service(is_service_account=True)
    tenant_app = _make_tenant_app(is_service_account=True)

    service.service_account_auth_service.refresh_access_token.return_value = {
        "access_token": "mock-token",
        "refresh_token": "old-refresh",
    }

    mock_client = AsyncMock()
    mock_client.get_sites.return_value = {"value": [_make_site("site-1")]}
    mock_client.get_followed_sites.return_value = [_make_site("site-2")]
    mock_client.get_group_connected_sites.return_value = []
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "intric.integration.infrastructure.preview_service.sharepoint_preview_service.SharePointContentClient",
        return_value=mock_client,
    ):
        result = await service.get_preview_info_with_app(tenant_app)

    assert len(result) == 2
    # Verify multi-source methods were called
    mock_client.get_sites.assert_called_once()
    mock_client.get_followed_sites.assert_called_once()
    mock_client.get_group_connected_sites.assert_called_once()


@pytest.mark.asyncio
async def test_tenant_app_uses_only_search():
    """Tenant app (application permissions) should only use get_sites search."""
    service = _make_service()
    tenant_app = _make_tenant_app(is_service_account=False)

    service.tenant_app_auth_service.get_access_token.return_value = "mock-token"

    mock_client = AsyncMock()
    mock_client.get_sites.return_value = {"value": [_make_site("site-1")]}
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "intric.integration.infrastructure.preview_service.sharepoint_preview_service.SharePointContentClient",
        return_value=mock_client,
    ):
        result = await service.get_preview_info_with_app(tenant_app)

    assert len(result) == 1
    # Should NOT call multi-source methods
    mock_client.get_followed_sites.assert_not_called()
    mock_client.get_group_connected_sites.assert_not_called()


@pytest.mark.asyncio
async def test_get_group_site_returns_none_on_404():
    """get_group_site should return None when the group has no site (404)."""
    import aiohttp

    from intric.integration.infrastructure.clients.sharepoint_content_client import (
        SharePointContentClient,
    )

    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 50 * 1024 * 1024

    with patch(
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        error = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=404,
            message="Not Found",
        )
        client.client = AsyncMock()
        client.client.get = AsyncMock(side_effect=error)

        result = await client.get_group_site("group-123")
        assert result is None
    finally:
        pass


@pytest.mark.asyncio
async def test_get_group_site_returns_none_on_403():
    """get_group_site should return None when access is forbidden (403)."""
    import aiohttp

    from intric.integration.infrastructure.clients.sharepoint_content_client import (
        SharePointContentClient,
    )

    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 50 * 1024 * 1024

    with patch(
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        error = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=403,
            message="Forbidden",
        )
        client.client = AsyncMock()
        client.client.get = AsyncMock(side_effect=error)

        result = await client.get_group_site("group-456")
        assert result is None
    finally:
        pass
