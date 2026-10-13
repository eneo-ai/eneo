from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from eneo.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)


def _unauthorized() -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=401, message="expired"
    )


@pytest.mark.asyncio
async def test_401_is_retried_with_a_token_from_the_access_token_provider():
    client = SharePointContentClient(
        base_url="https://graph.microsoft.com",
        api_token="stale",
        access_token_provider=AsyncMock(return_value="fresh"),
        max_download_bytes=1,
    )
    client.client = MagicMock()
    client.client.get = AsyncMock(
        side_effect=[_unauthorized(), {"value": [{"id": "1"}]}]
    )

    items = await client.get_folder_items(site_id="s", drive_id="d", folder_id="f")

    assert [item["id"] for item in items] == ["1"]
    assert client.headers["Authorization"] == "Bearer fresh"
    retry_headers = client.client.get.await_args_list[1].kwargs["headers"]
    assert retry_headers["Authorization"] == "Bearer fresh"


@pytest.mark.asyncio
async def test_401_without_any_refresh_path_propagates():
    client = SharePointContentClient(
        base_url="https://graph.microsoft.com",
        api_token="stale",
        max_download_bytes=1,
    )
    client.client = MagicMock()
    client.client.get = AsyncMock(side_effect=[_unauthorized()])

    with pytest.raises(aiohttp.ClientResponseError):
        await client.get_folder_items(site_id="s", drive_id="d", folder_id="f")
    assert client.client.get.await_count == 1


@pytest.mark.asyncio
async def test_uses_settings_default_max_download_bytes_when_not_overridden():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "eneo.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        assert client.max_download_bytes == 12_345_678
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_explicit_max_download_bytes_overrides_settings():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "eneo.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
            max_download_bytes=2_048,
        )

    try:
        assert client.max_download_bytes == 2_048
    finally:
        await client.client.close()
