from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from intric.main.models import ModelId
from intric.predefined_roles.predefined_role import PredefinedRoleInDB
from intric.roles.permissions import Permission
from intric.users import user_router
from intric.users.user import PropUserInvite, PropUserUpdate, UserState
from tests.fixtures import TEST_USER


async def test_invite_user_passes_tenant_to_service():
    user_service = AsyncMock()
    audit_service = AsyncMock()
    session = AsyncMock()

    new_user = TEST_USER.model_copy(update={"id": uuid4(), "email": "invitee@test.com"})
    user_service.invite_user.return_value = new_user

    container = SimpleNamespace(
        user_service=lambda: user_service,
        user=lambda: TEST_USER,
        session=lambda: session,
        audit_service=lambda: audit_service,
    )

    user_invite = PropUserInvite(email="invitee@test.com")

    result = await user_router.invite_user(user_invite=user_invite, container=container)

    assert result == new_user
    user_service.invite_user.assert_awaited_with(
        user_invite, tenant_id=TEST_USER.tenant_id
    )
    audit_service.log_async.assert_awaited()


async def test_invite_user_fetches_predefined_role_details():
    user_service = AsyncMock()
    audit_service = AsyncMock()
    session = AsyncMock()

    role_id = uuid4()
    role = SimpleNamespace(id=role_id, name="Editor", permissions=[Permission.ADMIN])
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: role)

    new_user = TEST_USER.model_copy(update={"id": uuid4(), "email": "invitee@test.com"})
    user_service.invite_user.return_value = new_user

    container = SimpleNamespace(
        user_service=lambda: user_service,
        user=lambda: TEST_USER,
        session=lambda: session,
        audit_service=lambda: audit_service,
    )

    user_invite = PropUserInvite(
        email="invitee@test.com", predefined_role=ModelId(id=role_id)
    )

    result = await user_router.invite_user(user_invite=user_invite, container=container)

    assert result == new_user
    session.execute.assert_awaited()
    audit_service.log_async.assert_awaited()


async def test_update_user_maps_prop_update_to_user_update_public():
    user_service = AsyncMock()
    audit_service = AsyncMock()

    role_id = uuid4()
    predefined_role = PredefinedRoleInDB(
        id=role_id,
        name="Editor",
        permissions=[Permission.ADMIN],
    )

    old_user = TEST_USER
    updated_user = TEST_USER.model_copy(
        update={
            "state": UserState.INACTIVE,
            "predefined_roles": [predefined_role],
        }
    )

    user_service.get_user.return_value = old_user
    user_service.update_user.return_value = updated_user

    container = SimpleNamespace(
        user_service=lambda: user_service,
        user=lambda: TEST_USER,
        audit_service=lambda: audit_service,
    )

    user_update = PropUserUpdate(
        predefined_role=ModelId(id=role_id),
        state=UserState.INACTIVE,
    )

    result = await user_router.update_user(
        id=TEST_USER.id,
        user_update=user_update,
        container=container,
    )

    assert result == updated_user
    user_service.update_user.assert_awaited()
    _, kwargs = user_service.update_user.call_args
    update_public = kwargs["user_update_public"]
    assert update_public.state == UserState.INACTIVE
    assert update_public.predefined_roles == [ModelId(id=role_id)]
    audit_service.log_async.assert_awaited()
