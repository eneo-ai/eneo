from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from intric.integration.infrastructure.clients.sharepoint_content_client import (
    SharePointContentClient,
)


@pytest.mark.asyncio
async def test_uses_settings_default_max_download_bytes_when_not_overridden():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
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
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
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


@pytest.mark.asyncio
async def test_get_my_unified_groups_falls_back_to_unfiltered_lookup_on_unsupported_filter():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        unsupported_filter_error = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=400,
            message="Request_UnsupportedQuery",
        )
        client.client = AsyncMock()
        client.client.get = AsyncMock(
            side_effect=[
                unsupported_filter_error,
                {
                    "value": [
                        {"id": "group-1", "displayName": "Unified Group", "groupTypes": ["Unified"]},
                        {"id": "group-2", "displayName": "Security Group", "groupTypes": []},
                    ]
                },
            ]
        )

        groups = await client.get_my_unified_groups()

        assert len(groups) == 1
        assert groups[0]["id"] == "group-1"
        assert groups[0]["displayName"] == "Unified Group"
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_get_group_connected_sites_is_best_effort():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        client.get_my_unified_groups = AsyncMock(
            return_value=[{"id": "g1"}, {"id": "g2"}, {"id": "g3"}]
        )

        async def _group_site_side_effect(group_id: str):
            if group_id == "g2":
                raise RuntimeError("transient error")
            return {"id": f"site-{group_id}"}

        client.get_group_site = AsyncMock(side_effect=_group_site_side_effect)

        sites = await client.get_group_connected_sites(max_concurrency=2)

        assert [s["id"] for s in sites] == ["site-g1", "site-g3"]
    finally:
        await client.client.close()


@pytest.mark.asyncio
async def test_get_my_unified_groups_fallback_keeps_groups_when_group_types_missing():
    settings = MagicMock()
    settings.sharepoint_max_download_bytes = 12_345_678

    with patch(
        "intric.integration.infrastructure.clients.sharepoint_content_client.get_settings",
        return_value=settings,
    ):
        client = SharePointContentClient(
            base_url="https://graph.microsoft.com",
            api_token="mock-token",
        )

    try:
        unsupported_filter_error = aiohttp.ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=400,
            message="Request_UnsupportedQuery",
        )
        client.client = AsyncMock()
        client.client.get = AsyncMock(
            side_effect=[
                unsupported_filter_error,
                {
                    "value": [
                        {"id": "group-1", "displayName": "No Types"},
                        {"id": "group-2", "displayName": "Security", "groupTypes": []},
                    ]
                },
            ]
        )

        groups = await client.get_my_unified_groups()

        assert len(groups) == 1
        assert groups[0]["id"] == "group-1"
    finally:
        await client.client.close()
