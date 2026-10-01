"""Token acquisition preserves the identity approved by the integration service."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.integration.application.sharepoint_auth_router import SharePointAuthRouter
from eneo.integration.domain.entities.oauth_token import SharePointToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.main.exceptions import BadRequestException
from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue


@pytest.fixture
def token_router(integration_access):
    token = SharePointToken(
        access_token="personal-token",
        refresh_token="personal-refresh",
        token_type=IntegrationType.Sharepoint,
        user_integration=integration_access.integration,
    )
    oauth = AsyncMock()
    oauth.get_oauth_token_by_user_integration.return_value = token
    app_auth = AsyncMock()
    app_auth.get_access_token.return_value = "organization-token"
    account_auth = AsyncMock()
    account_auth.refresh_access_token.return_value = {
        "access_token": "service-account-token",
        "refresh_token": "rotated-refresh",
    }
    return SharePointAuthRouter(
        tenant_app_service=AsyncMock(),
        tenant_app_auth_service=app_auth,
        oauth_token_service=oauth,
        service_account_auth_service=account_auth,
    )


async def test_oauth_selection_never_switches_to_organization_credentials(
    integration_access, token_router
):
    case = integration_access
    connection = await case.service.get_authorized_integration(
        case.integration.id, space=case.space
    )
    token = await token_router.get_token_for_integration(connection)
    assert token.access_token == "personal-token"
    assert token.user_integration.id == case.integration.id
    token_router.tenant_app_auth_service.get_access_token.assert_not_awaited()
    token_router.tenant_app_service.get_active_app_for_tenant.assert_not_awaited()


async def test_oauth_selection_in_shared_space_acquires_no_credentials(
    integration_access, token_router
):
    case = integration_access
    case.space.user_id = None
    case.space.tenant_space_id = uuid4()
    case.space.members[case.user.id] = SpaceMember(
        id=case.user.id, email=case.user.email, role=SpaceRoleValue.EDITOR
    )
    with pytest.raises(BadRequestException):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )
    token_router.oauth_token_service.get_oauth_token_by_user_integration.assert_not_awaited()
    token_router.tenant_app_auth_service.get_access_token.assert_not_awaited()


@pytest.mark.parametrize(
    "auth_method, expected",
    [
        ("tenant_app", "organization-token"),
        ("service_account", "service-account-token"),
    ],
)
async def test_organization_selection_uses_its_approved_app(
    integration_access, token_router, auth_method, expected
):
    case = integration_access
    case.use_organization_connection()
    case.app.auth_method = auth_method
    connection = await case.service.get_authorized_integration(
        case.integration.id, space=case.space
    )
    token = await token_router.get_token_for_integration(connection)
    assert token.access_token == expected
    assert token.user_integration.id == case.integration.id
    token_router.oauth_token_service.get_oauth_token_by_user_integration.assert_not_awaited()
    if auth_method == "service_account":
        assert case.app.service_account_refresh_token == "rotated-refresh"
        token_router.tenant_app_service.update.assert_awaited_once_with(case.app)


async def test_missing_oauth_token_is_an_explicit_failure(
    integration_access, token_router
):
    connection = await integration_access.service.get_authorized_integration(
        integration_access.integration.id
    )
    token_router.oauth_token_service.get_oauth_token_by_user_integration.return_value = None
    with pytest.raises(ValueError, match="No OAuth token"):
        await token_router.get_token_for_integration(connection)
    token_router.tenant_app_auth_service.get_access_token.assert_not_awaited()


@pytest.mark.parametrize("auth_method", ["tenant_app", "service_account"])
async def test_failed_organization_token_never_switches_identity(
    integration_access, token_router, auth_method
):
    case = integration_access
    case.use_organization_connection()
    case.app.auth_method = auth_method
    connection = await case.service.get_authorized_integration(case.integration.id)
    app_token = token_router.tenant_app_auth_service.get_access_token
    service_token = token_router.service_account_auth_service.refresh_access_token
    selected, other = (
        (service_token, app_token)
        if auth_method == "service_account"
        else (app_token, service_token)
    )
    selected.side_effect = RuntimeError("unavailable")
    with pytest.raises(ValueError, match="Failed to acquire access token"):
        await token_router.get_token_for_integration(connection)
    other.assert_not_awaited()
    token_router.oauth_token_service.get_oauth_token_by_user_integration.assert_not_awaited()
