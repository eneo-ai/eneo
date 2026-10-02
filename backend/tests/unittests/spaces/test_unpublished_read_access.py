"""Reading one assistant or app by ID, with the real space policy."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.actors import ActorFactory
from eneo.actors.actors.space_actor import SpaceAccessFacts, SpaceRoleFact
from eneo.apps.apps.app_service import AppService
from eneo.assistants.assistant_service import AssistantService
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.users.user import UserInDB


def member_actor(user: UserInDB, role: str):
    user = user.model_copy(deep=True)
    user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Member",
            tenant_id=user.tenant_id,
            permissions=[Permission.ASSISTANTS, Permission.APPS],
        )
    ]
    facts = SpaceAccessFacts(
        id=uuid4(),
        tenant_id=user.tenant_id,
        user_id=None,
        tenant_space_id=uuid4(),
        members={user.id: SpaceRoleFact(id=user.id, role=role)},
        group_members={},
        default_assistant_id=None,
        assistant_ids=frozenset(),
        app_ids=frozenset(),
    )
    return ActorFactory().create_space_actor(user=user, space=facts)


def shared_space(resource):
    space = MagicMock()
    space.is_personal.return_value = False
    space.default_assistant = None
    space.get_assistant.return_value = resource
    space.get_app.return_value = resource
    return space


def assistant_service(actor, space) -> AssistantService:
    service = AssistantService.__new__(AssistantService)
    service.actor_manager = MagicMock()
    service.actor_manager.get_space_actor_from_space.return_value = actor
    service.space_repo = AsyncMock()
    service.space_repo.get_space_by_assistant.return_value = space
    return service


def app_service(actor, space) -> AppService:
    service = AppService.__new__(AppService)
    service.actor_manager = MagicMock()
    service.actor_manager.get_space_actor_from_space.return_value = actor
    service.space_repo = AsyncMock()
    service.space_repo.get_space_by_app.return_value = space
    return service


@pytest.mark.parametrize(
    "role, published, allowed",
    [
        ("viewer", True, True),
        ("viewer", False, False),
        ("editor", False, True),
        ("admin", False, True),
    ],
)
async def test_unpublished_assistant_is_hidden_from_viewers(
    user, role, published, allowed
):
    assistant = MagicMock(id=uuid4(), published=published)
    service = assistant_service(member_actor(user, role), shared_space(assistant))

    if allowed:
        found, _ = await service.get_assistant(assistant.id)
        assert found is assistant
        assert await service.get_assistant_mcp_servers(assistant.id) is not None
    else:
        with pytest.raises(UnauthorizedException):
            await service.get_assistant(assistant.id)
        with pytest.raises(UnauthorizedException):
            await service.get_assistant_mcp_servers(assistant.id)


@pytest.mark.parametrize(
    "role, published, allowed",
    [
        ("viewer", True, True),
        ("viewer", False, False),
        ("editor", False, True),
        ("admin", False, True),
    ],
)
async def test_unpublished_app_is_hidden_from_viewers(user, role, published, allowed):
    app = MagicMock(id=uuid4(), published=published)
    service = app_service(member_actor(user, role), shared_space(app))

    if allowed:
        found, _ = await service.get_app(app.id)
        assert found is app
    else:
        with pytest.raises(UnauthorizedException):
            await service.get_app(app.id)
