from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.integration.application.website_integration_service import (
    SitemapPage,
    WebsiteIntegrationService,
)
from intric.integration.presentation.models import (
    WebsiteIntegrationConfigCreate,
    WebsiteIntegrationHeader,
)
from intric.main.exceptions import BadRequestException


def _make_service() -> WebsiteIntegrationService:
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[],
    )
    return WebsiteIntegrationService(
        session=AsyncMock(),
        user=user,
        space_service=AsyncMock(),
        job_service=AsyncMock(),
        website_crud_service=AsyncMock(),
        text_processor=AsyncMock(),
        datastore=AsyncMock(),
        info_blob_repo=AsyncMock(),
        aiohttp_session=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_create_config_requires_non_blank_name():
    service = _make_service()
    service._get_enabled_website_tenant_integration = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(id=uuid4())
    )
    service._resolve_owner = AsyncMock(return_value=(uuid4(), service.user.id))  # type: ignore[method-assign]

    with pytest.raises(BadRequestException, match="name is required"):
        await service.create_config(
            owner_type="user",
            payload=WebsiteIntegrationConfigCreate(
                name="   ",
                sitemap_url="https://example.com/sitemap.xml",
                headers=[],
            ),
        )


@pytest.mark.asyncio
async def test_create_config_requires_non_blank_sitemap_url():
    service = _make_service()
    service._get_enabled_website_tenant_integration = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(id=uuid4())
    )
    service._resolve_owner = AsyncMock(return_value=(uuid4(), service.user.id))  # type: ignore[method-assign]

    with pytest.raises(BadRequestException, match="Sitemap URL is required"):
        await service.create_config(
            owner_type="user",
            payload=WebsiteIntegrationConfigCreate(
                name="Marketing",
                sitemap_url="   ",
                headers=[],
            ),
        )


def test_headers_to_dict_strips_keys_and_ignores_blank_entries():
    result = WebsiteIntegrationService._headers_to_dict(
        [
            WebsiteIntegrationHeader(key=" Authorization ", value=" Bearer token "),
            WebsiteIntegrationHeader(key=" ", value="ignored"),
            WebsiteIntegrationHeader(key="api-key", value=" secret "),
        ]
    )

    assert result == {
        "Authorization": "Bearer token",
        "api-key": "secret",
    }


def test_parse_lastmod_supports_zulu_timestamps():
    parsed = WebsiteIntegrationService._parse_lastmod("2026-06-04T12:30:00Z")

    assert parsed == datetime(2026, 6, 4, 12, 30, tzinfo=timezone.utc)


def test_page_needs_sync_uses_lastmod_when_available():
    existing = SimpleNamespace(
        last_synced_at=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc),
        sitemap_lastmod=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc),
    )

    assert (
        WebsiteIntegrationService._page_needs_sync(
            existing,
            SitemapPage(
                url="https://example.com/a",
                lastmod=datetime(2026, 6, 4, 9, 0, tzinfo=timezone.utc),
            ),
        )
        is True
    )
    assert (
        WebsiteIntegrationService._page_needs_sync(
            existing,
            SitemapPage(
                url="https://example.com/a",
                lastmod=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc),
            ),
        )
        is False
    )
