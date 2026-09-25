import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.entities.tenant_sharepoint_app import (
    AUTH_METHOD_SERVICE_ACCOUNT,
    AUTH_METHOD_TENANT_APP,
    TenantSharePointApp,
)
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.preview_service import (
    sharepoint_preview_service as preview_module,
)
from eneo.integration.infrastructure.preview_service.sharepoint_preview_service import (
    SharePointPreviewService,
)

CLIENT_PATCH = (
    "eneo.integration.infrastructure.preview_service.sharepoint_preview_service."
    "SharePointContentClient"
)


def _make_service(
    *,
    tenant_app_auth_service: MagicMock | None = None,
    service_account_auth_service: MagicMock | None = None,
) -> SharePointPreviewService:
    return SharePointPreviewService(
        oauth_token_service=MagicMock(),
        tenant_app_auth_service=tenant_app_auth_service,
        service_account_auth_service=service_account_auth_service,
    )


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


def _sites_data() -> dict:
    return {
        "value": [
            {
                "displayName": preview.name,
                "id": preview.key,
                "webUrl": preview.url,
            }
            for preview in _site_previews()
        ]
    }


def _team_site_map() -> dict[str, dict[str, str]]:
    return {
        "group-my": {
            "id": "site-my",
            "webUrl": "https://contoso.sharepoint.com/sites/my-team",
        }
    }


def _content_client_context(content_client: MagicMock) -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=content_client)
    context.__aexit__ = AsyncMock(return_value=None)
    return context


def _sharepoint_token() -> SharePointToken:
    return SharePointToken(
        id=uuid4(),
        access_token="access-token",
        refresh_token="refresh-token",
        token_type=IntegrationType.Sharepoint,
        user_integration=MagicMock(),
    )


def _tenant_app(auth_method: str) -> TenantSharePointApp:
    return TenantSharePointApp(
        id=uuid4(),
        tenant_id=uuid4(),
        client_id="client-id",
        client_secret="client-secret",
        tenant_domain="contoso.onmicrosoft.com",
        auth_method=auth_method,
        service_account_refresh_token=(
            "service-refresh-token"
            if auth_method == AUTH_METHOD_SERVICE_ACCOUNT
            else None
        ),
    )


def test_marks_sites_backed_by_users_groups_as_my_teams():
    service = _make_service()

    categories = service._categorize_my_team_sites(
        site_previews=_site_previews(),
        team_site_map=_team_site_map(),
    )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS
    assert categories["site-other"] == service.CATEGORY_OTHER_SITES


def test_matches_by_normalized_url_when_site_id_differs():
    service = _make_service()
    team_site_map = _team_site_map()
    team_site_map["group-my"] = {
        "id": "some-other-id",
        "webUrl": "https://contoso.sharepoint.com/sites/My-Team/",
    }

    categories = service._categorize_my_team_sites(
        site_previews=_site_previews(),
        team_site_map=team_site_map,
    )

    assert categories["site-my"] == service.CATEGORY_MY_TEAMS


def test_no_team_site_map_returns_other_sites():
    service = _make_service()

    categories = service._categorize_my_team_sites(
        site_previews=_site_previews(),
        team_site_map={},
    )

    assert all(c == service.CATEGORY_OTHER_SITES for c in categories.values())


@pytest.mark.asyncio
async def test_member_lookup_failure_degrades_to_other_sites():
    service = _make_service()
    content_client = MagicMock()
    content_client.get_sites = AsyncMock(return_value=_sites_data())
    content_client.get_my_member_group_ids = AsyncMock(
        side_effect=RuntimeError("memberOf unavailable")
    )
    content_client.get_group_root_sites_batched = AsyncMock()

    previews = await service._load_site_previews(
        content_client=content_client,
        include_my_teams=True,
    )

    assert all(p.category == service.CATEGORY_OTHER_SITES for p in previews)
    content_client.get_group_root_sites_batched.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_preview_bounds_all_optional_graph_requests():
    service = _make_service()
    content_client = MagicMock()
    content_client.get_sites = AsyncMock(return_value=_sites_data())

    async def never_finishes():
        await asyncio.sleep(60)

    content_client.get_my_member_group_ids = AsyncMock(side_effect=never_finishes)
    content_client.get_group_root_sites_batched = AsyncMock()
    content_client.get_my_drive = AsyncMock(side_effect=never_finishes)

    with (
        patch(CLIENT_PATCH, return_value=_content_client_context(content_client)),
        patch.object(preview_module, "OPTIONAL_USER_CONTEXT_TIMEOUT_SECONDS", 0.01),
    ):
        previews = await asyncio.wait_for(
            service.get_preview_info(token=_sharepoint_token()),
            timeout=1.0,
        )

    assert [preview.key for preview in previews] == ["site-my", "site-other"]
    assert all(p.category == service.CATEGORY_OTHER_SITES for p in previews)
    content_client.get_group_root_sites_batched.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_preview_includes_my_teams_and_onedrive():
    service = _make_service()
    content_client = MagicMock()
    content_client.get_sites = AsyncMock(return_value=_sites_data())
    content_client.get_my_member_group_ids = AsyncMock(return_value=["group-my"])
    content_client.get_group_root_sites_batched = AsyncMock(
        return_value=_team_site_map()
    )
    content_client.get_my_drive = AsyncMock(
        return_value={
            "id": "drive-id",
            "webUrl": "https://contoso-my.sharepoint.com/personal/user",
            "owner": {"user": {"displayName": "Ada"}},
        }
    )

    with patch(
        CLIENT_PATCH,
        return_value=_content_client_context(content_client),
    ):
        previews = await service.get_preview_info(token=_sharepoint_token())

    categories = {preview.key: preview.category for preview in previews}
    assert categories == {
        "site-my": service.CATEGORY_MY_TEAMS,
        "site-other": service.CATEGORY_OTHER_SITES,
        "drive-id": service.CATEGORY_ONEDRIVE,
    }


@pytest.mark.asyncio
async def test_service_account_preview_includes_my_teams():
    service_account_auth_service = MagicMock()
    service_account_auth_service.refresh_access_token = AsyncMock(
        return_value={"access_token": "service-access-token"}
    )
    service = _make_service(service_account_auth_service=service_account_auth_service)
    content_client = MagicMock()
    content_client.get_sites = AsyncMock(return_value=_sites_data())
    content_client.get_my_member_group_ids = AsyncMock(return_value=["group-my"])
    content_client.get_group_root_sites_batched = AsyncMock(
        return_value=_team_site_map()
    )

    with patch(
        CLIENT_PATCH,
        return_value=_content_client_context(content_client),
    ):
        previews = await service.get_preview_info_with_app(
            tenant_app=_tenant_app(AUTH_METHOD_SERVICE_ACCOUNT)
        )

    categories = {preview.key: preview.category for preview in previews}
    assert categories["site-my"] == service.CATEGORY_MY_TEAMS
    assert categories["site-other"] == service.CATEGORY_OTHER_SITES
    content_client.get_my_member_group_ids.assert_awaited_once_with()
    content_client.get_group_root_sites_batched.assert_awaited_once_with(["group-my"])


@pytest.mark.asyncio
async def test_tenant_app_preview_skips_user_context():
    tenant_app_auth_service = MagicMock()
    tenant_app_auth_service.get_access_token = AsyncMock(
        return_value="tenant-app-access-token"
    )
    service = _make_service(tenant_app_auth_service=tenant_app_auth_service)
    content_client = MagicMock()
    content_client.get_sites = AsyncMock(return_value=_sites_data())
    content_client.get_my_member_group_ids = AsyncMock()
    content_client.get_group_root_sites_batched = AsyncMock()

    with patch(
        CLIENT_PATCH,
        return_value=_content_client_context(content_client),
    ):
        previews = await service.get_preview_info_with_app(
            tenant_app=_tenant_app(AUTH_METHOD_TENANT_APP)
        )

    assert all(p.category == service.CATEGORY_OTHER_SITES for p in previews)
    content_client.get_my_member_group_ids.assert_not_awaited()
    content_client.get_group_root_sites_batched.assert_not_awaited()
