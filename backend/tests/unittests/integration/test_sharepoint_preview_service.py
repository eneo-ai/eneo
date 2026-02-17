from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.integration.domain.entities.integration_preview import IntegrationPreview
from intric.integration.infrastructure.preview_service.sharepoint_preview_service import (
    SharePointPreviewService,
)


@pytest.mark.asyncio
async def test_classifies_my_teams_and_public_non_member_teams():
    service = SharePointPreviewService(oauth_token_service=MagicMock())
    content_client = MagicMock()
    content_client.get_teams = AsyncMock(
        return_value=[
            {"id": "group-my", "visibility": "Private"},
            {"id": "group-public", "visibility": "Public"},
        ]
    )
    content_client.get_my_member_group_ids = AsyncMock(return_value=["group-my"])

    async def get_group_root_site(group_id: str):
        if group_id == "group-my":
            return {
                "id": "site-my",
                "webUrl": "https://contoso.sharepoint.com/sites/my-team",
            }
        if group_id == "group-public":
            return {
                "id": "site-public",
                "webUrl": "https://contoso.sharepoint.com/sites/public-team",
            }
        return None

    content_client.get_group_root_site = AsyncMock(side_effect=get_group_root_site)

    site_previews = [
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

    categories = await service._classify_site_categories(
        content_client=content_client,
        site_previews=site_previews,
    )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS
    assert categories["site-public"] == service.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER
    assert categories["site-other"] == service.CATEGORY_OTHER_SITES


@pytest.mark.asyncio
async def test_classification_falls_back_to_unknown_when_graph_membership_fails():
    service = SharePointPreviewService(oauth_token_service=MagicMock())
    content_client = MagicMock()
    content_client.get_teams = AsyncMock(side_effect=RuntimeError("Forbidden"))
    content_client.get_my_member_group_ids = AsyncMock(return_value=[])

    site_previews = [
        IntegrationPreview(
            name="Site A",
            key="site-a",
            url="https://contoso.sharepoint.com/sites/a",
            type="site",
        ),
        IntegrationPreview(
            name="Site B",
            key="site-b",
            url="https://contoso.sharepoint.com/sites/b",
            type="site",
        ),
    ]

    categories = await service._classify_site_categories(
        content_client=content_client,
        site_previews=site_previews,
    )

    assert categories["site-a"] == service.CATEGORY_UNKNOWN
    assert categories["site-b"] == service.CATEGORY_UNKNOWN


@pytest.mark.asyncio
async def test_classification_falls_back_to_visibility_only_when_memberof_unavailable():
    service = SharePointPreviewService(oauth_token_service=MagicMock())
    content_client = MagicMock()
    content_client.get_teams = AsyncMock(
        return_value=[
            {"id": "group-public", "visibility": "Public"},
            {"id": "group-private", "visibility": "Private"},
        ]
    )
    content_client.get_my_member_group_ids = AsyncMock(
        side_effect=RuntimeError("memberOf not available")
    )

    async def get_group_root_site(group_id: str):
        if group_id == "group-public":
            return {
                "id": "site-public",
                "webUrl": "https://contoso.sharepoint.com/sites/public-team",
            }
        if group_id == "group-private":
            return {
                "id": "site-private",
                "webUrl": "https://contoso.sharepoint.com/sites/private-team",
            }
        return None

    content_client.get_group_root_site = AsyncMock(side_effect=get_group_root_site)

    site_previews = [
        IntegrationPreview(
            name="Public Team Site",
            key="site-public",
            url="https://contoso.sharepoint.com/sites/public-team",
            type="site",
        ),
        IntegrationPreview(
            name="Private Team Site",
            key="site-private",
            url="https://contoso.sharepoint.com/sites/private-team",
            type="site",
        ),
    ]

    categories = await service._classify_site_categories(
        content_client=content_client,
        site_previews=site_previews,
    )

    assert categories["site-public"] == service.CATEGORY_PUBLIC_TEAMS_NOT_MEMBER
    assert categories["site-private"] == service.CATEGORY_OTHER_SITES
