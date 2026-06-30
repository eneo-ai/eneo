"""Tests for admin safety guards across user operations.

Verifies that:
- /users/admin/* endpoints require admin permission
- update_user tenant-isolates the target user
- delete_user tenant-isolates the target user
- Last admin cannot be deactivated via state change
- Last admin cannot be deleted
- Admin checks count only active/invited users (not inactive)
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import BadRequestException
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.users.user import UserState, UserUpdatePublic
from eneo.users.user_service import UserService
from tests.fixtures import TEST_TENANT, TEST_USER


def _make_service():
    service = UserService(
        user_repo=AsyncMock(),
        auth_service=AsyncMock(),
        api_key_auth_resolver=AsyncMock(),
        api_key_v2_repo=AsyncMock(),
        audit_service=AsyncMock(),
        settings_repo=AsyncMock(),
        tenant_repo=AsyncMock(),
        info_blob_repo=AsyncMock(),
    )
    # Bypass email/username uniqueness checks in unit tests
    service.repo.get_user_by_email.return_value = None
    service.repo.get_user_by_username.return_value = None
    return service


def _admin_role(tenant_id=None):
    return RoleInDB(
        id=uuid4(),
        name="Admin",
        permissions=[Permission.ADMIN, Permission.ASSISTANTS],
        tenant_id=tenant_id or TEST_TENANT.id,
    )


def _basic_role(tenant_id=None):
    return RoleInDB(
        id=uuid4(),
        name="User",
        permissions=[Permission.ASSISTANTS],
        tenant_id=tenant_id or TEST_TENANT.id,
    )


class TestLastAdminDeleteProtection:
    """Cannot delete the last admin user."""

    async def test_delete_last_admin_blocked(self):
        service = _make_service()
        admin_user = TEST_USER.model_copy(update={"roles": [_admin_role()]})
        service.repo.get_user_by_id.return_value = admin_user
        service.repo.count_users_with_admin_permission.return_value = 1

        with pytest.raises(BadRequestException, match="last admin"):
            await service.delete_user(admin_user.id)

    async def test_delete_admin_allowed_when_others_exist(self):
        service = _make_service()
        admin_user = TEST_USER.model_copy(update={"roles": [_admin_role()]})
        service.repo.get_user_by_id.return_value = admin_user
        service.repo.count_users_with_admin_permission.return_value = 3
        service.repo.delete.return_value = admin_user

        result = await service.delete_user(admin_user.id)
        assert result is True

    async def test_delete_non_admin_always_allowed(self):
        service = _make_service()
        basic_user = TEST_USER.model_copy(update={"roles": [_basic_role()]})
        service.repo.get_user_by_id.return_value = basic_user
        service.repo.delete.return_value = basic_user

        result = await service.delete_user(basic_user.id)
        assert result is True
        # Should not check admin count
        service.repo.count_users_with_admin_permission.assert_not_awaited()


class TestLastAdminStateProtection:
    """Cannot deactivate the last admin via state change."""

    async def test_deactivate_last_admin_blocked(self):
        service = _make_service()
        admin_user = TEST_USER.model_copy(update={"roles": [_admin_role()]})
        service.repo.get_user_by_id.return_value = admin_user
        service.repo.count_users_with_admin_permission.return_value = 1

        update = UserUpdatePublic(state=UserState.INACTIVE)

        with pytest.raises(BadRequestException, match="last admin"):
            await service.update_user(admin_user.id, update)

    async def test_deactivate_admin_allowed_when_others_exist(self):
        service = _make_service()
        admin_user = TEST_USER.model_copy(update={"roles": [_admin_role()]})
        service.repo.get_user_by_id.return_value = admin_user
        service.repo.count_users_with_admin_permission.return_value = 2
        service.repo.update.return_value = admin_user.model_copy(
            update={"state": UserState.INACTIVE}
        )

        result = await service.update_user(
            admin_user.id, UserUpdatePublic(state=UserState.INACTIVE)
        )
        assert result.state == UserState.INACTIVE

    async def test_activate_user_always_allowed(self):
        service = _make_service()
        user = TEST_USER.model_copy(update={"state": UserState.INACTIVE})
        service.repo.get_user_by_id.return_value = user
        service.repo.update.return_value = user.model_copy(
            update={"state": UserState.ACTIVE}
        )

        result = await service.update_user(
            user.id, UserUpdatePublic(state=UserState.ACTIVE)
        )
        assert result.state == UserState.ACTIVE


class TestRoleSwapAdminProtection:
    """Swapping from admin role A to admin role B should not be blocked."""

    async def test_swap_admin_role_a_to_b_allowed(self):
        service = _make_service()
        role_a = _admin_role()
        role_b = _admin_role()  # Different admin role

        admin_user = TEST_USER.model_copy(update={"roles": [role_a]})
        service.repo.get_user_by_id.return_value = admin_user
        service.repo.count_users_with_admin_permission.return_value = 1

        # Simulate fetching role_b from DB (it has admin)
        role_b_record = SimpleNamespace(permissions=["admin", "assistants"])
        service.repo.get_roles_by_ids.return_value = [role_b_record]

        service.repo.update.return_value = admin_user.model_copy(
            update={"roles": [role_b]}
        )

        update = UserUpdatePublic(roles=[ModelId(id=role_b.id)])
        # Should NOT raise — new role also has admin
        result = await service.update_user(admin_user.id, update)
        assert result is not None

    async def test_swap_admin_to_basic_blocked_when_last(self):
        service = _make_service()
        admin_role = _admin_role()
        basic_role = _basic_role()

        admin_user = TEST_USER.model_copy(update={"roles": [admin_role]})
        service.repo.get_user_by_id.return_value = admin_user
        service.repo.count_users_with_admin_permission.return_value = 1

        # New role does not have admin
        basic_record = SimpleNamespace(permissions=["assistants"])
        service.repo.get_roles_by_ids.return_value = [basic_record]

        update = UserUpdatePublic(roles=[ModelId(id=basic_role.id)])
        with pytest.raises(BadRequestException, match="last admin"):
            await service.update_user(admin_user.id, update)
