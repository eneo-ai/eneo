from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.spaces.api.space_models import SpaceRoleValue
from intric.spaces.space_service import SpaceService
from tests.fixtures import TEST_USER


@pytest.fixture
def actor():
    return MagicMock()


@pytest.fixture
def service(actor: MagicMock):
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor

    service = SpaceService(
        repo=AsyncMock(),
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
