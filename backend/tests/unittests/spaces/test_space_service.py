from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException, UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.space_service import SpaceService
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


async def test_raise_unauthorized_if_user_can_not_edit(
    service: SpaceService, actor: MagicMock
):
    actor.can_edit_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.update_space(uuid4(), MagicMock())


async def test_raise_unauthorized_if_user_can_not_delete(
    service: SpaceService, actor: MagicMock
):
    actor.can_delete_space.return_value = False

    with pytest.raises(UnauthorizedException):
        await service.delete_space(uuid4())


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
