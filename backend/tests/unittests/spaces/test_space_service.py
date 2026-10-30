from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    UnauthorizedException,
)
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.space_factory import SpaceFactory
from eneo.spaces.space_service import SpaceService
from eneo.spaces.space_update import LinkEdit
from tests.fixtures import TEST_USER


@pytest.fixture
def actor():
    return MagicMock()


@pytest.fixture
def service(actor: MagicMock):
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor
    actor_manager.get_space_actor.return_value = actor

    # Mock the repo with proper session.execute chain for MCP servers query
    repo = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    repo.session.execute.return_value = mock_result

    service = SpaceService(
        repo=repo,
        completion_model_crud_service=AsyncMock(),
        transcription_model_crud_service=AsyncMock(),
        embedding_model_crud_service=AsyncMock(),
        factory=MagicMock(),
        user_repo=AsyncMock(),
        user=TEST_USER,
        actor_manager=actor_manager,
        completion_model_service=AsyncMock(),
        transcription_model_service=AsyncMock(),
        security_classification_service=AsyncMock(),
        icon_repo=AsyncMock(),
        user_groups_repo=AsyncMock(),
    )

    return service


async def test_create_space_is_created_with_latest_available_embedding_model(
    service: SpaceService,
):
    space = MagicMock()
    embedding_models = [
        MagicMock(created_at=datetime(2024, 1, 3 - i), can_access=True)
        for i in range(3)
    ]
    service.factory.create_space.return_value = space
    service.embedding_model_crud_service.get_embedding_models.return_value = (
        embedding_models
    )

    await service.create_space(MagicMock())

    assert space.embedding_models == [embedding_models[0]]


async def test_a_new_space_has_no_mcp_server_until_its_admin_activates_one(
    service: SpaceService,
):
    # Kills the mutant that gives a new space every enabled server: a space
    # admin activates the servers the space may use. Capabilities are not
    # servers a space picks, and a new space still offers the tenant's.
    space = SpaceFactory.create_space(name="space", tenant_id=TEST_USER.tenant_id)
    service.factory.create_space.return_value = space
    service.completion_model_service.get_available_completion_models.return_value = []
    service.transcription_model_service.get_default_model.return_value = None
    service.embedding_model_crud_service.get_embedding_models.return_value = []
    service.repo.session.execute.return_value.scalars.return_value.all.return_value = [
        MagicMock(purpose="general", tenant_id=TEST_USER.tenant_id),
        MagicMock(purpose="web_search", tenant_id=TEST_USER.tenant_id),
    ]

    await service.create_space("space")

    assert space.mcp_servers == []
    assert space.enabled_capabilities == ["web_search"]


async def test_raise_not_found_if_user_not_member_of_space(
    service: SpaceService, actor: MagicMock
):
    actor.can_read_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.get_space(uuid4())


async def test_get_applications_projection_authorizes_sparse_access_facts(
    service: SpaceService, actor: MagicMock
):
    projection = MagicMock()
    service.repo.get_applications_projection.return_value = projection
    actor.can_read_space.return_value = True
    space_id = uuid4()

    result = await service.get_applications_projection(space_id)

    assert result is projection
    service.repo.get_applications_projection.assert_awaited_once_with(space_id)
    service.actor_manager.get_space_actor.assert_called_once_with(projection.access)


async def test_get_applications_projection_rejects_unauthorized_access(
    service: SpaceService, actor: MagicMock
):
    service.repo.get_applications_projection.return_value = MagicMock()
    actor.can_read_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.get_applications_projection(uuid4())


async def test_the_transcription_space_is_read_for_the_space_the_actor_reads(
    service: SpaceService, actor: MagicMock
):
    space = MagicMock()
    service.repo.get_transcription_space.return_value = space
    actor.can_read_space.return_value = True
    actor.space.id = uuid4()

    assert await service.get_transcription_space(actor) is space
    service.repo.get_transcription_space.assert_awaited_once_with(actor.space.id)


async def test_the_transcription_space_refuses_an_actor_get_space_refuses(
    service: SpaceService, actor: MagicMock
):
    actor.can_read_space.return_value = False

    with pytest.raises(UnauthorizedException) as refused:
        await service.get_transcription_space(actor)
    with pytest.raises(UnauthorizedException) as refused_full:
        await service.get_space(uuid4())

    assert (str(refused.value), refused.value.code, refused.value.context) == (
        str(refused_full.value),
        refused_full.value.code,
        refused_full.value.context,
    )
    service.repo.get_transcription_space.assert_not_awaited()


async def test_raise_unauthorized_if_user_can_not_edit(
    service: SpaceService, actor: MagicMock
):
    actor.can_edit_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.update_space(uuid4(), MagicMock())


@pytest.mark.parametrize(("new_level", "removes_below"), [(20, None), (30, 30)])
async def test_only_a_change_of_level_removes_the_links_below_it(
    service: SpaceService, new_level: int, removes_below: int | None
):
    """Kills the mutant that derives the link removal from the classification
    being sent (``is_provided``) instead of a change of its level: restating
    the space's level must not delete the links below it, raising it must."""
    current = SecurityClassification(
        tenant_id=TEST_USER.tenant_id,
        name="K20",
        security_level=20,
        security_enabled=True,
    )
    sent = SecurityClassification(
        tenant_id=TEST_USER.tenant_id,
        name=f"K{new_level}",
        security_level=new_level,
        security_enabled=True,
    )
    space = SpaceFactory.create_space(name="space", tenant_id=TEST_USER.tenant_id)
    space.security_classification = current
    service.repo.one.return_value = space
    service.user = TEST_USER.model_copy(
        update={
            "tenant": TEST_USER.tenant.model_copy(update={"security_enabled": True})
        }
    )
    service.security_classification_service.get_security_classification.return_value = (
        sent
    )

    await service.update_space(space.id, security_classification=ModelId(id=uuid4()))

    (_, change), _ = service.repo.update_settings.await_args
    assert change.minimum_security_level == removes_below


@pytest.mark.parametrize(
    ("argument", "loaded", "field"),
    [
        ("embedding_model_ids", "linked_embedding_models", "embedding_models"),
        (
            "transcription_model_ids",
            "linked_transcription_models",
            "transcription_models",
        ),
    ],
)
async def test_a_link_list_edit_is_scoped_to_the_links_the_space_showed(
    service: SpaceService, argument: str, loaded: str, field: str
):
    """Kills, per list: update_space scopes the edit to the usable models
    only, to no links, or to another list's, instead of the ones the loaded
    space shows. The completion and MCP server lists have integration
    killers (test_explicit_removal_unlinks_the_model, test_space_mcp_audit)."""
    shown_id = uuid4()
    space = MagicMock()
    for name in (
        "linked_completion_models",
        "linked_embedding_models",
        "linked_transcription_models",
        "mcp_servers",
    ):
        setattr(space, name, [MagicMock(id=uuid4())])
    setattr(space, loaded, [MagicMock(id=shown_id)])
    service.repo.one.return_value = space

    await service.update_space(uuid4(), **{argument: []})

    (_, change), _ = service.repo.update_settings.await_args
    assert getattr(change, field) == LinkEdit((), frozenset({shown_id}))


async def test_raise_unauthorized_if_user_can_not_delete(
    service: SpaceService, actor: MagicMock
):
    actor.can_delete_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.delete_space(uuid4())


async def test_delete_space_rejects_flow_delete_blockers_before_side_effects(
    service: SpaceService, actor: MagicMock
):
    actor.can_delete_space.return_value = True
    space_id = uuid4()
    space = MagicMock(
        id=space_id,
        icon_id=uuid4(),
        assistants=[],
        apps=[],
    )
    service.get_space = AsyncMock(return_value=space)
    service.repo.has_flow_delete_blockers.return_value = True
    service.repo.has_active_legal_hold.return_value = False
    service.api_key_scope_revoker = AsyncMock()

    with pytest.raises(ConflictException) as exc_info:
        await service.delete_space(space_id)

    assert exc_info.value.code == "space_contains_flow_delete_blockers"
    assert str(exc_info.value) == (
        "Space contains Flow history or Flow-owned draft resources. "
        "Remove draft Flows first; spaces with Flow run history require "
        "Flow data purge before deletion."
    )
    service.api_key_scope_revoker.revoke_scope.assert_not_awaited()
    service.repo.delete.assert_not_awaited()
    service.icon_repo.delete_if_unreferenced.assert_not_awaited()


async def test_only_admins_can_add_members(service: SpaceService, actor: MagicMock):
    actor.can_edit_space.return_value = False

    service.user_repo.get_user_by_id_and_tenant_id.return_value = MagicMock(
        email="test@test.com", username="username"
    )

    with pytest.raises(UnauthorizedException):
        await service.add_member(MagicMock(), MagicMock(), role=SpaceRoleValue.EDITOR)


async def test_only_admins_can_delete_members(service: SpaceService, actor: MagicMock):
    actor.can_edit_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.remove_member(MagicMock(), MagicMock())


async def test_can_not_remove_self(service: SpaceService):
    id = uuid4()
    service.user = MagicMock(id=id)

    with pytest.raises(BadRequestException):
        await service.remove_member(MagicMock(), id)


async def test_only_admins_can_change_role_of_member(
    service: SpaceService, actor: MagicMock
):
    actor.can_edit_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.change_role_of_member(MagicMock(), MagicMock(), MagicMock())


async def test_can_not_change_role_of_self(service: SpaceService):
    id = uuid4()
    service.user = MagicMock(id=id)

    with pytest.raises(BadRequestException):
        await service.change_role_of_member(MagicMock(), id, MagicMock())


async def test_get_spaces_and_personal_space_returns_personal_space_first(
    service: SpaceService,
):
    personal_space = MagicMock()
    other_spaces = [MagicMock(), MagicMock(), MagicMock()]

    service.repo.get_personal_space.return_value = personal_space
    service.repo.get_spaces_for_member.return_value = other_spaces

    spaces = await service.get_spaces(include_personal=True)

    assert spaces == [personal_space] + other_spaces


async def test_get_spaces_passes_include_applications_to_repo(
    service: SpaceService,
):
    service.repo.get_spaces_for_member.return_value = []

    await service.get_spaces(include_applications=True)

    service.repo.get_spaces_for_member.assert_called_once_with(
        include_applications=True
    )


async def test_get_spaces_defaults_include_applications_to_false(
    service: SpaceService,
):
    service.repo.get_spaces_for_member.return_value = []

    await service.get_spaces()

    service.repo.get_spaces_for_member.assert_called_once_with(
        include_applications=False
    )


async def test_delete_space_names_a_legal_hold_as_the_blocker(
    service: SpaceService, actor: MagicMock
):
    actor.can_delete_space.return_value = True
    space_id = uuid4()
    service.get_space = AsyncMock(
        return_value=MagicMock(id=space_id, icon_id=None, assistants=[], apps=[])
    )
    service.repo.has_flow_delete_blockers.return_value = True
    service.repo.has_active_legal_hold.return_value = True
    service.api_key_scope_revoker = AsyncMock()

    with pytest.raises(ConflictException) as exc_info:
        await service.delete_space(space_id)

    assert exc_info.value.code == "space_contains_legal_hold"
    service.repo.delete.assert_not_awaited()
    service.api_key_scope_revoker.revoke_scope.assert_not_awaited()


@pytest.mark.parametrize(
    ("is_admin", "lists_organization"), [(True, True), (False, False)]
)
async def test_get_spaces_lists_the_organization_space_only_for_admins(
    service: SpaceService, is_admin: bool, lists_organization: bool
):
    """A former admin's membership row must not keep the space in their list."""
    organization = MagicMock(user_id=None, tenant_space_id=None)
    shared = MagicMock(user_id=None, tenant_space_id=uuid4())
    service.repo.get_spaces_for_member.return_value = [organization, shared]
    service.user = MagicMock(permissions={Permission.ADMIN} if is_admin else set())

    spaces = await service.get_spaces()

    assert spaces == ([organization, shared] if lists_organization else [shared])


def _organization_space(member_ids: list) -> MagicMock:
    hub = MagicMock(id=uuid4())
    hub.members = {member_id: MagicMock(id=member_id) for member_id in member_ids}
    hub.remove_member.side_effect = lambda user_id: hub.members.pop(user_id)
    return hub


def _admin(user_id) -> MagicMock:
    return MagicMock(id=user_id, username=f"admin-{user_id}", email=f"{user_id}@x.se")


async def test_ensure_org_admin_members_makes_the_members_exactly_the_admins(
    service: SpaceService,
):
    admin, new_admin, former_admin = uuid4(), uuid4(), uuid4()
    hub = _organization_space([admin, former_admin])
    service.user_repo.list_tenant_admins.return_value = [
        _admin(admin),
        _admin(new_admin),
    ]
    reloaded = MagicMock()
    service.repo.one.return_value = reloaded

    result = await service.ensure_org_admin_members(hub)

    added = service.repo.add_member.await_args_list
    assert [(call.args[0], call.args[1].id) for call in added] == [(hub.id, new_admin)]
    service.repo.remove_member.assert_awaited_once_with(hub.id, former_admin)
    assert set(hub.members) == {admin, new_admin}
    assert result is reloaded


async def test_ensure_org_admin_members_leaves_an_up_to_date_space_alone(
    service: SpaceService,
):
    admin = uuid4()
    hub = _organization_space([admin])
    service.user_repo.list_tenant_admins.return_value = [_admin(admin)]

    assert await service.ensure_org_admin_members(hub) is hub
    service.repo.add_member.assert_not_awaited()
    service.repo.remove_member.assert_not_awaited()
    service.repo.one.assert_not_awaited()
