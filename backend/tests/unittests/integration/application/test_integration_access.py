"""Connection authorization and import rights, using the real space policy."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import aiohttp
import pytest

from eneo.integration.application.integration_knowledge_service import (
    IntegrationKnowledgeService,
)
from eneo.integration.application.integration_preview_service import (
    IntegrationPreviewService,
)
from eneo.integration.domain.entities.oauth_token import OauthToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    CREDENTIALS_INVALID_MESSAGE,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceGroupMember, SpaceMember, SpaceRoleValue
from eneo.users.user import UserGroupInDBRead


async def test_owner_can_use_personal_connection(integration_access):
    case = integration_access
    connection = await case.service.get_authorized_integration(
        case.integration.id, space=case.space
    )
    assert connection.integration is case.integration
    assert connection.tenant_app is None


@pytest.mark.parametrize("admin", [False, True])
async def test_other_personal_connection_is_hidden_even_from_admin(
    integration_access, admin
):
    case = integration_access
    case.integration.user_id = uuid4()
    if admin:
        case.user.roles[0].permissions.append(Permission.ADMIN)
    with pytest.raises(NotFoundException):
        await case.service.get_authorized_integration(case.integration.id)


@pytest.mark.parametrize("resource", ["integration", "space", "app", "app_link"])
async def test_foreign_tenant_or_mismatched_app_is_hidden(integration_access, resource):
    case = integration_access
    case.use_organization_connection()
    if resource == "integration":
        case.integration.tenant_integration.tenant_id = uuid4()
    elif resource == "space":
        case.space.tenant_id = uuid4()
    elif resource == "app":
        case.app.tenant_id = uuid4()
    else:
        case.integration.tenant_app_id = uuid4()
    with pytest.raises(NotFoundException):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


@pytest.mark.parametrize("kind", ["personal", "shared", "organization"])
async def test_nonmember_cannot_use_space(integration_access, kind):
    case = integration_access
    case.space.user_id = uuid4() if kind == "personal" else None
    case.space.tenant_space_id = uuid4() if kind == "shared" else None
    with pytest.raises(NotFoundException):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


async def test_viewer_cannot_browse_remote_content(integration_access):
    case = integration_access
    case.space.user_id = None
    case.space.tenant_space_id = uuid4()
    case.space.members[case.user.id] = SpaceMember(
        id=case.user.id, email=case.user.email, role=SpaceRoleValue.VIEWER
    )
    with pytest.raises(UnauthorizedException):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


async def test_group_editor_can_use_organization_connection(integration_access):
    case = integration_access
    case.use_organization_connection()
    group_id = uuid4()
    case.user.user_groups = [UserGroupInDBRead(id=group_id, name="Editors")]
    case.space.members.clear()
    case.space.group_members[group_id] = SpaceGroupMember(
        id=group_id, name="Editors", role=SpaceRoleValue.EDITOR
    )
    connection = await case.service.get_authorized_integration(
        case.integration.id, space=case.space
    )
    assert connection.integration.id == case.integration.id
    assert connection.tenant_app is case.app


@pytest.mark.parametrize(
    ("space_type", "admin"),
    [("shared", False), ("shared", True), ("organization", True)],
)
async def test_personal_connection_is_limited_to_personal_space(
    integration_access, space_type, admin
):
    case = integration_access
    if admin:
        case.user.roles[0].permissions.append(Permission.ADMIN)
    case.space.user_id = None
    case.space.tenant_space_id = uuid4() if space_type == "shared" else None
    case.space.members[case.user.id] = SpaceMember(
        id=case.user.id, email=case.user.email, role=SpaceRoleValue.ADMIN
    )
    with pytest.raises(BadRequestException, match="personal space"):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


async def test_a_former_admin_cannot_use_the_organization_space(integration_access):
    """Their membership row outlives the admin role, but grants nothing: the
    space is not even shown to exist."""
    case = integration_access
    case.space.user_id = None
    case.space.tenant_space_id = None
    case.space.members[case.user.id] = SpaceMember(
        id=case.user.id, email=case.user.email, role=SpaceRoleValue.ADMIN
    )
    with pytest.raises(NotFoundException, match="Space not found"):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


async def test_space_owner_still_needs_integration_permission(integration_access):
    case = integration_access
    case.user.roles[0].permissions.clear()
    with pytest.raises(UnauthorizedException):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


async def test_tenant_app_requires_admin_even_for_space_editor(integration_access):
    case = integration_access
    case.use_organization_connection()
    case.user.roles[0].permissions.remove(Permission.ADMIN)
    with pytest.raises(UnauthorizedException, match="Admin permission"):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


@pytest.mark.parametrize("auth_method", ["tenant_app", "service_account"])
async def test_admin_can_use_exact_active_organization_connection(
    integration_access, auth_method
):
    case = integration_access
    case.use_organization_connection()
    case.app.auth_method = auth_method
    connection = await case.service.get_authorized_integration(
        case.integration.id, space=case.space
    )
    assert connection.tenant_app is case.app


@pytest.mark.parametrize(
    "invalid",
    ["inactive", "unauthenticated", "unknown_auth", "personal_space", "missing_app"],
)
async def test_invalid_connection_is_rejected(integration_access, invalid):
    case = integration_access
    case.use_organization_connection()
    if invalid == "inactive":
        case.app.is_active = False
    elif invalid == "unauthenticated":
        case.integration.authenticated = False
    elif invalid == "unknown_auth":
        case.integration.auth_type = "unknown"
    elif invalid == "personal_space":
        case.space.user_id = case.user.id
    else:
        case.integration.tenant_app_id = None
    with pytest.raises(BadRequestException):
        await case.service.get_authorized_integration(
            case.integration.id, space=case.space
        )


async def test_raw_app_id_cannot_substitute_for_integration_id(integration_access):
    case = integration_access
    case.use_organization_connection()
    with pytest.raises(NotFoundException):
        await case.service.get_authorized_integration(case.app.id)


async def test_available_connections_require_space_access(integration_access):
    case = integration_access
    case.space.user_id = uuid4()
    with pytest.raises(NotFoundException):
        await case.service.get_available_integrations_for_space(case.space)


async def test_new_import_cannot_bypass_connection_owner(integration_access):
    case = integration_access
    case.integration.user_id = uuid4()
    space_repo = AsyncMock()
    space_repo.one.return_value = case.space
    jobs, knowledge, tokens = AsyncMock(), AsyncMock(), AsyncMock()
    service = IntegrationKnowledgeService(
        user=case.user,
        user_integration_service=case.service,
        space_repo=space_repo,
        job_service=jobs,
        integration_knowledge_repo=knowledge,
        oauth_token_repo=tokens,
        embedding_model_repo=AsyncMock(),
        actor_manager=case.service.actor_manager,
        sharepoint_subscription_service=AsyncMock(),
        tenant_sharepoint_app_repo=case.app_repo,
        tenant_app_auth_service=AsyncMock(),
        org_token_provider=AsyncMock(),
    )
    with pytest.raises(NotFoundException):
        await service.create_space_integration_knowledge(
            user_integration_id=case.integration.id,
            name="Private",
            embedding_model_id=uuid4(),
            space_id=case.space.id,
            key="private-site",
            url="https://example.com/private",
        )
    knowledge.add.assert_not_awaited()
    jobs.queue_job.assert_not_awaited()
    tokens.one.assert_not_awaited()


async def test_owned_confluence_preview_still_works(integration_access):
    case = integration_access
    case.integration.tenant_integration.integration.integration_type = "confluence"
    tokens = AsyncMock()
    tokens.one.return_value = OauthToken(
        access_token="confluence-token",
        refresh_token="refresh",
        token_type=IntegrationType.Confluence,
        user_integration=case.integration,
    )
    confluence = AsyncMock()
    confluence.get_preview_info.return_value = []
    service = IntegrationPreviewService(
        oauth_token_repo=tokens,
        user_integration_service=case.service,
        confluence_preview_service=confluence,
        sharepoint_preview_service=AsyncMock(),
    )
    assert await service.get_preview_data(case.integration.id) == []
    confluence.get_preview_info.assert_awaited_once_with(token=tokens.one.return_value)


def _graph_refusal(status: int) -> aiohttp.ClientResponseError:
    return aiohttp.ClientResponseError(
        request_info=MagicMock(), history=(), status=status, message="refused"
    )


async def test_confluence_preview_refusal_keeps_its_original_error(
    integration_access,
):
    case = integration_access
    case.integration.tenant_integration.integration.integration_type = "confluence"
    tokens = AsyncMock()
    tokens.one.return_value = OauthToken(
        access_token="confluence-token",
        refresh_token="refresh",
        token_type=IntegrationType.Confluence,
        user_integration=case.integration,
    )
    confluence = AsyncMock()
    confluence.get_preview_info.side_effect = _graph_refusal(401)
    service = IntegrationPreviewService(
        oauth_token_repo=tokens,
        user_integration_service=case.service,
        confluence_preview_service=confluence,
        sharepoint_preview_service=AsyncMock(),
    )
    with pytest.raises(aiohttp.ClientResponseError) as exc_info:
        await service.get_preview_data(case.integration.id)
    assert exc_info.value.status == 401


async def test_sharepoint_preview_refusal_becomes_a_credential_message(
    integration_access,
):
    case = integration_access
    tokens = AsyncMock()
    tokens.one.return_value = OauthToken(
        access_token="sharepoint-token",
        refresh_token="refresh",
        token_type=IntegrationType.Sharepoint,
        user_integration=case.integration,
    )
    sharepoint = AsyncMock()
    sharepoint.get_preview_info.side_effect = _graph_refusal(401)
    service = IntegrationPreviewService(
        oauth_token_repo=tokens,
        user_integration_service=case.service,
        confluence_preview_service=AsyncMock(),
        sharepoint_preview_service=sharepoint,
    )
    with pytest.raises(BadRequestException, match=CREDENTIALS_INVALID_MESSAGE) as error:
        await service.get_preview_data(case.integration.id)
    # The same code an import or a sync answers with.
    assert getattr(error.value, "code", None) == "sharepoint_credentials_invalid"
