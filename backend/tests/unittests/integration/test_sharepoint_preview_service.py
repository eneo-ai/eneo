from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.infrastructure.preview_service.sharepoint_preview_service import (
    SharePointPreviewService,
)

TENANT_ID = uuid4()

SETTINGS_PATCH = (
    "eneo.integration.infrastructure.preview_service."
    "sharepoint_preview_service.get_settings"
)


def _settings(enabled: bool = True, ttl: int = 21600) -> MagicMock:
    return MagicMock(
        sharepoint_site_categorization_enabled=enabled,
        sharepoint_preview_cache_ttl_seconds=ttl,
    )


def _make_service(cache: MagicMock | None) -> SharePointPreviewService:
    return SharePointPreviewService(
        oauth_token_service=MagicMock(),
        group_site_cache=cache,
    )


def _make_cache(
    entries: list[dict] | None,
    built_at: datetime | None = None,
) -> MagicMock:
    cache = MagicMock()
    if entries is None:
        cache.get = AsyncMock(return_value=None)
    else:
        cache.get = AsyncMock(
            return_value=(entries, built_at or datetime.now(timezone.utc))
        )
    cache.schedule_rebuild = AsyncMock(return_value=True)
    return cache


def _site_previews() -> list[IntegrationPreview]:
    return [
        IntegrationPreview(
            name="My Team Site",
            key="site-my",
            url="https://contoso.sharepoint.com/sites/my-team",
            type="site",
        ),
        IntegrationPreview(
            name="Public Team Site",
            key="site-public",
            url="https://contoso.sharepoint.com/sites/public-team",
            type="site",
        ),
        IntegrationPreview(
            name="Other Site",
            key="site-other",
            url="https://contoso.sharepoint.com/sites/other-site",
            type="site",
        ),
    ]


@pytest.mark.asyncio
async def test_classifies_my_teams_and_public_non_member_teams_from_cache():
    cache = _make_cache(
        [
            {
                "group_id": "group-my",
                "visibility": "private",
                "site_id": "site-my",
                "web_url": "https://contoso.sharepoint.com/sites/my-team",
            },
            {
                "group_id": "group-public",
                "visibility": "public",
                "site_id": "site-public",
                "web_url": "https://contoso.sharepoint.com/sites/public-team",
            },
        ]
    )
    service = _make_service(cache)

    with patch(SETTINGS_PATCH, return_value=_settings()):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids={"group-my"},
        )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS
    assert categories["site-public"] == service.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER
    assert categories["site-other"] == service.CATEGORY_OTHER_SITES
    cache.schedule_rebuild.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_miss_returns_other_sites_and_schedules_rebuild():
    cache = _make_cache(None)
    service = _make_service(cache)
    user_integration_id = uuid4()

    with patch(SETTINGS_PATCH, return_value=_settings()):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids={"group-my"},
            user_integration_id=user_integration_id,
        )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())
    cache.schedule_rebuild.assert_awaited_once_with(
        TENANT_ID,
        tenant_app_id=None,
        user_integration_id=user_integration_id,
    )


@pytest.mark.asyncio
async def test_visibility_only_classification_when_memberof_unavailable():
    cache = _make_cache(
        [
            {
                "group_id": "group-public",
                "visibility": "public",
                "site_id": "site-public",
                "web_url": "https://contoso.sharepoint.com/sites/public-team",
            },
            {
                "group_id": "group-my",
                "visibility": "private",
                "site_id": "site-my",
                "web_url": "https://contoso.sharepoint.com/sites/my-team",
            },
        ]
    )
    service = _make_service(cache)

    with patch(SETTINGS_PATCH, return_value=_settings()):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids=None,
        )

    assert categories["site-public"] == service.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER
    assert categories["site-my"] == service.CATEGORY_OTHER_SITES


@pytest.mark.asyncio
async def test_matches_sites_by_normalized_url_when_site_id_differs():
    cache = _make_cache(
        [
            {
                "group_id": "group-my",
                "visibility": "private",
                "site_id": "some-other-id",
                "web_url": "https://contoso.sharepoint.com/sites/My-Team/",
            },
        ]
    )
    service = _make_service(cache)

    with patch(SETTINGS_PATCH, return_value=_settings()):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids={"group-my"},
        )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS


@pytest.mark.asyncio
async def test_stale_cache_hit_still_classifies_but_schedules_refresh():
    stale_built_at = datetime.now(timezone.utc) - timedelta(hours=5)
    cache = _make_cache(
        [
            {
                "group_id": "group-public",
                "visibility": "public",
                "site_id": "site-public",
                "web_url": "https://contoso.sharepoint.com/sites/public-team",
            },
        ],
        built_at=stale_built_at,
    )
    service = _make_service(cache)

    with patch(SETTINGS_PATCH, return_value=_settings(ttl=21600)):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids=None,
        )

    assert categories["site-public"] == service.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER
    cache.schedule_rebuild.assert_awaited_once()


@pytest.mark.asyncio
async def test_categorization_disabled_skips_cache_entirely():
    cache = _make_cache([])
    service = _make_service(cache)

    with patch(SETTINGS_PATCH, return_value=_settings(enabled=False)):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids={"group-my"},
        )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())
    cache.get.assert_not_awaited()
    cache.schedule_rebuild.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_read_failure_degrades_to_uncategorized():
    cache = _make_cache([])
    cache.get = AsyncMock(side_effect=ConnectionError("redis down"))
    service = _make_service(cache)

    with patch(SETTINGS_PATCH, return_value=_settings()):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=TENANT_ID,
            member_group_ids={"group-my"},
        )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())
    cache.schedule_rebuild.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_tenant_or_cache_returns_default_without_error():
    service = _make_service(None)

    with patch(SETTINGS_PATCH, return_value=_settings()):
        categories = await service._classify_site_categories(
            site_previews=_site_previews(),
            tenant_id=None,
            member_group_ids=None,
        )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())
