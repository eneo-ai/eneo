"""Tests for admin permission protection.

Verifies that:
- Cannot remove 'admin' permission from the last admin role
- Cannot delete the last admin role
- Can remove 'admin' if other admins exist via other roles
- Can delete admin role if other admins exist via other roles
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.main.exceptions import BadRequestException
from intric.roles.permissions import Permission
from intric.roles.role import RoleInDB, RoleUpdateRequest
from intric.roles.roles_service import RolesService
from tests.fixtures import TEST_USER


def _make_service(user_repo=None) -> RolesService:
    repo = AsyncMock()
    service = RolesService(
        user=TEST_USER,
        repo=repo,
        user_repo=user_repo,
    )
    return service


def _make_admin_role() -> RoleInDB:
    return RoleInDB(
        id=uuid4(),
        name="Admin Role",
        permissions=[Permission.ADMIN, Permission.ASSISTANTS],
        tenant_id=TEST_USER.tenant_id,
    )


def _make_non_admin_role() -> RoleInDB:
    return RoleInDB(
        id=uuid4(),
        name="Basic Role",
        permissions=[Permission.ASSISTANTS],
        tenant_id=TEST_USER.tenant_id,
    )


class TestDeleteRoleAdminProtection:
    """Prevent deleting the last role that provides admin access."""

    async def test_delete_admin_role_blocked_when_last_admin(self):
        user_repo = AsyncMock()
        user_repo.count_users_with_admin_permission.return_value = 0  # no other admins

        service = _make_service(user_repo=user_repo)
        admin_role = _make_admin_role()
        service.repo.get_role.return_value = admin_role

        with pytest.raises(BadRequestException, match="only source of admin access"):
            await service.delete_role(admin_role.id)

    async def test_delete_admin_role_allowed_when_other_admins_exist(self):
        user_repo = AsyncMock()
        user_repo.count_users_with_admin_permission.return_value = 2  # other admins exist

        service = _make_service(user_repo=user_repo)
        admin_role = _make_admin_role()
        service.repo.get_role.return_value = admin_role
        service.repo.delete_role_by_id.return_value = admin_role

        result = await service.delete_role(admin_role.id)
        assert result == admin_role

    async def test_delete_non_admin_role_always_allowed(self):
        user_repo = AsyncMock()
        service = _make_service(user_repo=user_repo)
        role = _make_non_admin_role()
        service.repo.get_role.return_value = role
        service.repo.delete_role_by_id.return_value = role

        result = await service.delete_role(role.id)
        assert result == role
        # Should not even check admin count for non-admin roles
        user_repo.count_users_with_admin_permission.assert_not_awaited()


class TestUpdateRoleAdminProtection:
    """Prevent removing admin permission from the last admin role."""

    async def test_remove_admin_permission_blocked_when_last_admin(self):
        user_repo = AsyncMock()
        user_repo.count_users_with_admin_permission.return_value = 0

        service = _make_service(user_repo=user_repo)
        admin_role = _make_admin_role()
        service.repo.get_role.return_value = admin_role

        update = RoleUpdateRequest(permissions=[Permission.ASSISTANTS])  # removing admin

        with pytest.raises(BadRequestException, match="only source of admin access"):
            await service.update_role(update, admin_role.id)

    async def test_remove_admin_permission_allowed_when_other_admins_exist(self):
        user_repo = AsyncMock()
        user_repo.count_users_with_admin_permission.return_value = 3

        service = _make_service(user_repo=user_repo)
        admin_role = _make_admin_role()
        service.repo.get_role.return_value = admin_role

        updated_role = admin_role.model_copy(update={"permissions": [Permission.ASSISTANTS]})
        service.repo.update_role.return_value = updated_role

        update = RoleUpdateRequest(permissions=[Permission.ASSISTANTS])
        result = await service.update_role(update, admin_role.id)
        assert Permission.ADMIN not in result.permissions

    async def test_update_non_admin_role_skips_check(self):
        user_repo = AsyncMock()
        service = _make_service(user_repo=user_repo)
        role = _make_non_admin_role()
        service.repo.get_role.return_value = role

        updated = role.model_copy(update={"name": "Renamed"})
        service.repo.update_role.return_value = updated

        update = RoleUpdateRequest(name="Renamed")
        result = await service.update_role(update, role.id)
        assert result.name == "Renamed"
        user_repo.count_users_with_admin_permission.assert_not_awaited()

    async def test_keeping_admin_permission_is_fine(self):
        user_repo = AsyncMock()
        service = _make_service(user_repo=user_repo)
        admin_role = _make_admin_role()
        service.repo.get_role.return_value = admin_role

        updated = admin_role.model_copy(update={"name": "Super Admin"})
        service.repo.update_role.return_value = updated

        # Still includes ADMIN — should not trigger check
        update = RoleUpdateRequest(
            name="Super Admin",
            permissions=[Permission.ADMIN, Permission.ASSISTANTS],
        )
        result = await service.update_role(update, admin_role.id)
        assert result.name == "Super Admin"
        user_repo.count_users_with_admin_permission.assert_not_awaited()
