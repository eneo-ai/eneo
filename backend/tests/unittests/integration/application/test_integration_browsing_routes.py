"""HTTP contracts after authentication; real services and policy, no live servers."""

from dataclasses import dataclass
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from dependency_injector import providers
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from eneo.integration.domain.entities.integration_preview import IntegrationPreview
from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.repositories.oauth_token_repo import OauthTokenRepository
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.preview_service.sharepoint_tree_service import (
    SharePointTreeService,
)
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue


@dataclass
class BrowsingAPI:
    app: FastAPI
    tokens: AsyncMock
    app_tokens: AsyncMock
    service_tokens: AsyncMock
    preview: AsyncMock
    tree: AsyncMock


@pytest.fixture
def browsing_api(integration_access, monkeypatch, authenticated_integration_app):
    case = integration_access
    space_repo = AsyncMock()
    space_repo.one.return_value = case.space
    tokens = AsyncMock(spec=OauthTokenRepository)
    token = SharePointToken(
        access_token="fixture-token",
        refresh_token="fixture-refresh",
        token_type=IntegrationType.Sharepoint,
        user_integration=case.integration,
    )
    tokens.one.return_value = token
    tokens.one_or_none.return_value = token
    app_tokens = AsyncMock()
    app_tokens.get_access_token.return_value = "fixture-app-token"
    service_tokens = AsyncMock()
    service_tokens.refresh_access_token.return_value = {
        "access_token": "fixture-service-token",
        "refresh_token": "rotated-service-refresh",
    }
    preview = AsyncMock()
    preview.get_preview_info.return_value = [
        IntegrationPreview(
            name="Allowed site",
            url="https://example.com/site",
            type="site",
            key="site-1",
        )
    ]
    preview.get_preview_info_with_app.return_value = (
        preview.get_preview_info.return_value
    )
    tree = AsyncMock(
        return_value={"items": [], "current_path": "", "drive_id": "drive-1"}
    )
    monkeypatch.setattr(SharePointTreeService, "get_folder_tree", tree)

    # Supply the already authenticated actor at the request dependency boundary.
    # Keep production DI for all services under test so missing wiring also fails.
    container = Container(
        user=providers.Object(case.user),
        user_integration_repo=providers.Object(case.integration_repo),
        tenant_integration_repo=providers.Object(AsyncMock()),
        tenant_sharepoint_app_repo=providers.Object(case.app_repo),
        space_repo=providers.Object(space_repo),
        oauth_token_repo=providers.Object(tokens),
        tenant_app_auth_service=providers.Object(app_tokens),
        service_account_auth_service=providers.Object(service_tokens),
        sharepoint_preview_service=providers.Object(preview),
        sharepoint_subscription_service=providers.Object(AsyncMock()),
    )
    app = authenticated_integration_app(container)
    return BrowsingAPI(app, tokens, app_tokens, service_tokens, preview, tree)


@pytest.mark.parametrize("endpoint", ["preview", "tree"])
@pytest.mark.parametrize(
    "failure, expected, auth_method",
    [
        ("foreign_owner", 404, None),
        ("foreign_owner_admin", 404, None),
        ("foreign_tenant", 404, None),
        ("non_admin_app", 403, "tenant_app"),
        ("inactive_app", 400, "tenant_app"),
        ("raw_app_id", 404, "tenant_app"),
        ("foreign_app", 404, "tenant_app"),
        ("non_admin_app", 403, "service_account"),
        ("inactive_app", 400, "service_account"),
        ("raw_app_id", 404, "service_account"),
        ("foreign_app", 404, "service_account"),
    ],
)
async def test_unauthorized_browsing_is_stopped_before_credentials(
    integration_access, browsing_api, endpoint, failure, expected, auth_method
):
    case = integration_access
    if auth_method is not None:
        case.use_organization_connection()
        case.app.auth_method = auth_method
    requested_id = case.integration.id
    if failure.startswith("foreign_owner"):
        case.integration.user_id = uuid4()
        if failure.endswith("admin"):
            case.user.roles[0].permissions.append(Permission.ADMIN)
    elif failure == "foreign_tenant":
        case.integration.tenant_integration.tenant_id = uuid4()
    elif failure == "foreign_app":
        case.app.tenant_id = uuid4()
    elif failure == "non_admin_app":
        case.user.roles[0].permissions.remove(Permission.ADMIN)
    elif failure == "inactive_app":
        case.app.is_active = False
    else:
        requested_id = case.app.id
    suffix = "preview/" if endpoint == "preview" else "sharepoint/tree/"
    async with AsyncClient(
        transport=ASGITransport(app=browsing_api.app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/integrations/{requested_id}/{suffix}",
            params={"space_id": str(case.space.id), "drive_id": "drive-1"},
        )
    assert response.status_code == expected, response.text
    browsing_api.tokens.one.assert_not_awaited()
    browsing_api.tokens.one_or_none.assert_not_awaited()
    browsing_api.app_tokens.get_access_token.assert_not_awaited()
    browsing_api.service_tokens.refresh_access_token.assert_not_awaited()
    browsing_api.preview.get_preview_info.assert_not_awaited()
    browsing_api.preview.get_preview_info_with_app.assert_not_awaited()
    browsing_api.tree.assert_not_awaited()


@pytest.mark.parametrize(
    "failure, expected", [("tenant", 404), ("nonmember", 404), ("viewer", 403)]
)
async def test_tree_enforces_space_access(
    integration_access, browsing_api, failure, expected
):
    case = integration_access
    if failure == "tenant":
        case.space.tenant_id = uuid4()
    elif failure == "nonmember":
        case.space.user_id = uuid4()
    else:
        case.space.user_id = None
        case.space.tenant_space_id = uuid4()
        case.space.members[case.user.id] = SpaceMember(
            id=case.user.id,
            email=case.user.email,
            role=SpaceRoleValue.VIEWER,
        )
    async with AsyncClient(
        transport=ASGITransport(app=browsing_api.app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/integrations/{case.integration.id}/sharepoint/tree/",
            params={"space_id": str(case.space.id), "drive_id": "drive-1"},
        )
    assert response.status_code == expected, response.text
    browsing_api.tokens.one_or_none.assert_not_awaited()
    browsing_api.tree.assert_not_awaited()


@pytest.mark.parametrize(
    "access, expected",
    [
        ("viewer", 200),
        ("no_import_permission", 200),
        ("nonmember", 404),
        ("foreign_tenant", 404),
    ],
)
async def test_available_connections_preserve_knowledge_page_access(
    integration_access, browsing_api, access, expected
):
    case = integration_access
    case.app_repo.one_or_none = AsyncMock(return_value=None)
    if access == "viewer":
        case.space.user_id = None
        case.space.tenant_space_id = uuid4()
        case.space.members[case.user.id] = SpaceMember(
            id=case.user.id, email=case.user.email, role=SpaceRoleValue.VIEWER
        )
    elif access == "no_import_permission":
        case.user.roles[0].permissions.remove(Permission.INTEGRATIONS)
    elif access == "nonmember":
        case.space.user_id = uuid4()
    else:
        case.space.tenant_id = uuid4()

    # The knowledge page loads this list even for users who can only read it.
    async with AsyncClient(
        transport=ASGITransport(app=browsing_api.app), base_url="http://test"
    ) as client:
        response = await client.get(f"/integrations/spaces/{case.space.id}/available/")
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()["items"] == []
    browsing_api.tokens.one_or_none.assert_not_awaited()
    browsing_api.tree.assert_not_awaited()


@pytest.mark.parametrize(
    "auth_method, expected_token",
    [
        ("user_oauth", "fixture-token"),
        ("tenant_app", "fixture-app-token"),
        ("service_account", "fixture-service-token"),
    ],
)
async def test_authorized_preview_and_tree_still_work(
    integration_access, browsing_api, auth_method, expected_token
):
    case = integration_access
    if auth_method != "user_oauth":
        case.use_organization_connection()
        case.app.auth_method = auth_method
    if auth_method == "service_account":
        case.app.service_account_refresh_token = "configured-service-refresh"
    async with AsyncClient(
        transport=ASGITransport(app=browsing_api.app), base_url="http://test"
    ) as client:
        preview = await client.get(f"/integrations/{case.integration.id}/preview/")
        tree = await client.get(
            f"/integrations/{case.integration.id}/sharepoint/tree/",
            params={"space_id": str(case.space.id), "drive_id": "drive-1"},
        )
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["name"] == "Allowed site"
    assert tree.status_code == 200, tree.text
    assert tree.json()["drive_id"] == "drive-1"
    used_token = browsing_api.tree.call_args.kwargs["token"]
    assert used_token.access_token == expected_token
    if auth_method != "user_oauth":
        browsing_api.preview.get_preview_info_with_app.assert_awaited_once_with(
            tenant_app=case.app
        )
        browsing_api.tokens.one_or_none.assert_not_awaited()
    if auth_method == "service_account":
        assert case.app.service_account_refresh_token == "rotated-service-refresh"
        case.app_repo.update.assert_awaited_once_with(case.app)
        browsing_api.app_tokens.get_access_token.assert_not_awaited()
    else:
        browsing_api.service_tokens.refresh_access_token.assert_not_awaited()
