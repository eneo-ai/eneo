from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import AuthenticationException
from eneo.main.models import ModelId
from eneo.user_groups.user_group import UserGroupInDB, UserGroupUpdateRequest
from eneo.user_groups.user_groups_service import UserGroupsService
from eneo.users.user import UserInDBBase
from tests.fixtures import TEST_TENANT, TEST_USER, TEST_USER_2


@pytest.fixture(name="service")
def service_with_mocks():
    return UserGroupsService(
        repo=AsyncMock(),
        user=TEST_USER,
        audit_service=AsyncMock(),
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


def _person(username: str) -> UserInDBBase:
    return UserInDBBase(
        id=uuid4(),
        username=username,
        email=f"{username}@kommun.se",
        tenant_id=TEST_TENANT.id,
        used_tokens=0,
        state="active",
    )


def _group(*users: UserInDBBase) -> UserGroupInDB:
    return UserGroupInDB(
        id=GROUP_ID, name="IFO-handläggare", tenant_id=TEST_TENANT.id, users=list(users)
    )


GROUP_ID = uuid4()
SPACE_ID = uuid4()


def _audited(service: UserGroupsService) -> list[dict]:
    return [call.kwargs for call in service.audit_service.log_required.await_args_list]


@pytest.fixture
def group_space(service: UserGroupsService):
    service.repo.space_roles.return_value = [(SPACE_ID, "IFO", "editor")]


async def test_adding_a_user_is_always_logged_with_the_spaces_it_reaches(
    service: UserGroupsService, group_space
):
    anna = _person("anna")
    service.repo.get_user_group.return_value = _group()
    service.repo.update_user_group.return_value = _group(anna)

    await service.add_user(user_group_uuid=GROUP_ID, user_id=anna.id)

    (entry,) = _audited(service)
    assert entry["action"] == ActionType.USER_GROUP_MEMBER_ADDED
    assert (entry["entity_type"], entry["entity_id"]) == (
        EntityType.USER_GROUP,
        GROUP_ID,
    )
    assert entry["user"] is TEST_USER
    assert entry["description"] == "Added anna to user group 'IFO-handläggare'"
    assert entry["metadata"]["target"]["id"] == str(GROUP_ID)
    assert entry["metadata"]["extra"] == {
        "member": {"id": str(anna.id), "name": "anna", "email": "anna@kommun.se"},
        "spaces": [{"id": str(SPACE_ID), "name": "IFO", "role": "editor"}],
    }
    service.repo.space_roles.assert_awaited_once_with(GROUP_ID, TEST_TENANT.id)


async def test_removing_a_user_is_always_logged(
    service: UserGroupsService, group_space
):
    anna = _person("anna")
    service.repo.get_user_group.return_value = _group(anna)
    service.repo.update_user_group.return_value = _group()

    await service.remove_user(user_group_uuid=GROUP_ID, user_id=anna.id)

    (entry,) = _audited(service)
    assert entry["action"] == ActionType.USER_GROUP_MEMBER_REMOVED
    assert entry["description"] == "Removed anna from user group 'IFO-handläggare'"
    assert entry["metadata"]["extra"]["member"]["id"] == str(anna.id)


async def test_replacing_the_users_logs_each_one_added_and_removed(
    service: UserGroupsService, group_space
):
    anna, bo, cecilia = _person("anna"), _person("bo"), _person("cecilia")
    service.repo.get_user_group.return_value = _group(anna, bo)
    service.repo.update_user_group.return_value = _group(bo, cecilia)

    await service.update_user_group(
        UserGroupUpdateRequest(users=[ModelId(id=bo.id), ModelId(id=cecilia.id)]),
        user_group_uuid=GROUP_ID,
    )

    assert [
        (entry["action"], entry["metadata"]["extra"]["member"]["name"])
        for entry in _audited(service)
    ] == [
        (ActionType.USER_GROUP_MEMBER_ADDED, "cecilia"),
        (ActionType.USER_GROUP_MEMBER_REMOVED, "anna"),
    ]


async def test_changes_that_keep_the_members_log_nothing(
    service: UserGroupsService, group_space
):
    anna = _person("anna")
    service.repo.get_user_group.return_value = _group(anna)
    service.repo.update_user_group.return_value = _group(anna)

    await service.add_user(user_group_uuid=GROUP_ID, user_id=anna.id)
    await service.update_user_group(
        UserGroupUpdateRequest(name="IFO"), user_group_uuid=GROUP_ID
    )

    service.audit_service.log_required.assert_not_awaited()
    service.repo.space_roles.assert_not_awaited()


async def test_a_failed_audit_write_fails_the_change(
    service: UserGroupsService, group_space
):
    anna = _person("anna")
    service.repo.get_user_group.return_value = _group()
    service.repo.update_user_group.return_value = _group(anna)
    service.audit_service.log_required.side_effect = RuntimeError("audit down")

    with pytest.raises(RuntimeError, match="audit down"):
        await service.add_user(user_group_uuid=GROUP_ID, user_id=anna.id)
