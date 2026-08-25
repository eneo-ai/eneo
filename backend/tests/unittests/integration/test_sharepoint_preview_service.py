from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.infrastructure.preview_service.sharepoint_preview_service import (
    SharePointPreviewService,
)


def _make_service() -> SharePointPreviewService:
    return SharePointPreviewService(oauth_token_service=MagicMock())


def _make_content_client(site_map: dict | None) -> MagicMock:
    content_client = MagicMock()
    if site_map is None:
        content_client.get_group_root_sites_batched = AsyncMock(
            side_effect=RuntimeError("throttled")
        )
    else:
        content_client.get_group_root_sites_batched = AsyncMock(return_value=site_map)
    return content_client


def _site_previews() -> list[IntegrationPreview]:
    return [
        IntegrationPreview(
            name="My Team Site",
            key="site-my",
            url="https://contoso.sharepoint.com/sites/my-team",
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
async def test_marks_sites_backed_by_users_groups_as_my_teams():
    service = _make_service()
    content_client = _make_content_client(
        {
            "group-my": {
                "id": "site-my",
                "webUrl": "https://contoso.sharepoint.com/sites/my-team",
            }
        }
    )

    categories = await service._categorize_my_team_sites(
        content_client=content_client,
        site_previews=_site_previews(),
        member_group_ids=["group-my"],
    )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS
    assert categories["site-other"] == service.CATEGORY_OTHER_SITES
    content_client.get_group_root_sites_batched.assert_awaited_once_with(["group-my"])


@pytest.mark.asyncio
async def test_matches_by_normalized_url_when_site_id_differs():
    service = _make_service()
    content_client = _make_content_client(
        {
            "group-my": {
                "id": "some-other-id",
                "webUrl": "https://contoso.sharepoint.com/sites/My-Team/",
            }
        }
    )

    categories = await service._categorize_my_team_sites(
        content_client=content_client,
        site_previews=_site_previews(),
        member_group_ids=["group-my"],
    )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS


@pytest.mark.asyncio
async def test_no_member_groups_skips_lookup_and_returns_other_sites():
    service = _make_service()
    content_client = _make_content_client({})

    categories = await service._categorize_my_team_sites(
        content_client=content_client,
        site_previews=_site_previews(),
        member_group_ids=None,
    )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())
    content_client.get_group_root_sites_batched.assert_not_awaited()


@pytest.mark.asyncio
async def test_lookup_failure_degrades_to_other_sites():
    service = _make_service()
    content_client = _make_content_client(None)

    categories = await service._categorize_my_team_sites(
        content_client=content_client,
        site_previews=_site_previews(),
        member_group_ids=["group-my"],
    )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())


@pytest.mark.asyncio
async def test_slow_lookup_times_out_and_degrades_to_other_sites():
    import asyncio

    from eneo.integration.infrastructure.preview_service import (
        sharepoint_preview_service as module,
    )

    service = _make_service()
    content_client = MagicMock()

    async def never_finishes(_group_ids):
        await asyncio.sleep(60)

    content_client.get_group_root_sites_batched = never_finishes

    original_timeout = module.CATEGORIZATION_TIMEOUT_SECONDS
    module.CATEGORIZATION_TIMEOUT_SECONDS = 0.05
    try:
        categories = await service._categorize_my_team_sites(
            content_client=content_client,
            site_previews=_site_previews(),
            member_group_ids=["group-my"],
        )
    finally:
        module.CATEGORIZATION_TIMEOUT_SECONDS = original_timeout

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())
