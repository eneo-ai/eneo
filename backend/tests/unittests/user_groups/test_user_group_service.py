from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import AuthenticationException
from eneo.main.models import ModelId
from eneo.user_groups.user_group import UserGroupInDB, UserGroupUpdateRequest
from eneo.user_groups.user_groups_service import UserGroupsService
from tests.fixtures import TEST_TENANT, TEST_USER, TEST_USER_2


@pytest.fixture(name="service")
def service_with_mocks():
    return UserGroupsService(
        repo=AsyncMock(),
        user=TEST_USER,
    )


async def test_assign_users_to_user_group_fail(service: UserGroupsService):
    uuid = uuid4()
    user_group = UserGroupInDB(id=uuid, name="test name", tenant_id=TEST_TENANT.id)
    service.repo.get_user_group.return_value = user_group

    user_group.users = [TEST_USER_2]
    service.repo.update_user_group.return_value = user_group

    with pytest.raises(
        AuthenticationException,
        match=f"User {TEST_USER.id} tried to add user {TEST_USER_2.id} "
        f"to group {user_group.id}",
    ):
        user_group_in = UserGroupUpdateRequest(users=[ModelId(id=TEST_USER_2.id)])
        await service.update_user_group(user_group_in, user_group_uuid=uuid)


async def test_add_user_to_user_group_fail(service: UserGroupsService):
    uuid = uuid4()
    user_group = UserGroupInDB(id=uuid, name="test name", tenant_id=TEST_TENANT.id)
    service.repo.get_user_group.return_value = user_group

    user_group.users = [TEST_USER_2]
    service.repo.update_user_group.return_value = user_group

    with pytest.raises(
        AuthenticationException,
        match=f"User {TEST_USER.id} tried to add user {TEST_USER_2.id} "
        f"to group {user_group.id}",
    ):
        await service.add_user(user_group_uuid=uuid, user_id=TEST_USER_2.id)
