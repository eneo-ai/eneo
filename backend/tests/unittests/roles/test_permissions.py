"""Comprehensive tests for the permissions system.

Tests that:
- Each permission grants access only to its intended area
- Missing permissions correctly block access
- Permissions are independent (having one doesn't grant another)
- The validate_permission/validate_permissions helpers work correctly
- The UserInDB.permissions computed field aggregates from all roles
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import (
    Permission,
    validate_permission,
    validate_permissions,
)
from intric.roles.role import RoleInDB
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB

_TEST_TENANT = TenantInDB(id=uuid4(), name="test", quota_limit=1024**3)


def _make_user(*permissions: Permission) -> UserInDB:
    """Create a test user with exactly the specified permissions."""
    role = RoleInDB(
        id=uuid4(),
        name="test_role",
        permissions=list(permissions),
        tenant_id=_TEST_TENANT.id,
    )
    return UserInDB(
        id=uuid4(),
        username="testuser",
        email="test@test.com",
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=_TEST_TENANT.id,
        tenant=_TEST_TENANT,
        roles=[role],
        state="active",
    )


def _make_user_with_roles(*roles: RoleInDB) -> UserInDB:
    """Create a test user with multiple roles."""
    return UserInDB(
        id=uuid4(),
        username="testuser",
        email="test@test.com",
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=_TEST_TENANT.id,
        tenant=_TEST_TENANT,
        roles=list(roles),
        state="active",
    )


# --- Original decorator test ---


class MockService:
    def __init__(self, user: UserInDB):
        self.user = user

    @validate_permissions(Permission.ADMIN)
    async def func_in_need_of_validation(self, *args, **kwargs):
        1 / 0


async def test_validation_decorator():
    user = MagicMock(permissions=[Permission.ADMIN])
    service = MockService(user)

    with pytest.raises(ZeroDivisionError):
        await service.func_in_need_of_validation(3, 10, two=4)

    user.permissions = [Permission.AI]

    with pytest.raises(
        UnauthorizedException,
        match=f"Need permission {Permission.ADMIN.value} in order to access",
    ):
        await service.func_in_need_of_validation(45, "thing")


# --- validate_permission function tests ---


class TestValidatePermission:
    """Test the validate_permission function for each permission."""

    @pytest.mark.parametrize("permission", list(Permission))
    def test_user_with_permission_passes(self, permission: Permission):
        user = _make_user(permission)
        validate_permission(user, permission)

    @pytest.mark.parametrize("permission", list(Permission))
    def test_user_without_permission_fails(self, permission: Permission):
        user = _make_user()  # No permissions
        with pytest.raises(UnauthorizedException):
            validate_permission(user, permission)


class TestPermissionsAreIndependent:
    """Each permission should only grant access to its own area, not others."""

    @pytest.mark.parametrize("granted", list(Permission))
    def test_single_permission_does_not_grant_others(self, granted: Permission):
        user = _make_user(granted)
        for other in Permission:
            if other == granted:
                validate_permission(user, other)
            else:
                with pytest.raises(UnauthorizedException):
                    validate_permission(user, other)


# --- UserInDB.permissions aggregation tests ---


class TestUserPermissionsAggregation:
    """UserInDB.permissions should combine permissions from all assigned roles."""

    def test_no_roles_means_no_permissions(self):
        user = _make_user_with_roles()
        assert user.permissions == set()

    def test_single_role_permissions(self):
        user = _make_user(Permission.ASSISTANTS, Permission.COLLECTIONS)
        assert user.permissions == {Permission.ASSISTANTS, Permission.COLLECTIONS}

    def test_multiple_roles_combine_permissions(self):
        role1 = RoleInDB(
            id=uuid4(),
            name="role1",
            permissions=[Permission.ASSISTANTS, Permission.APPS],
            tenant_id=_TEST_TENANT.id,
        )
        role2 = RoleInDB(
            id=uuid4(),
            name="role2",
            permissions=[Permission.ADMIN, Permission.INSIGHTS],
            tenant_id=_TEST_TENANT.id,
        )
        user = _make_user_with_roles(role1, role2)
        assert user.permissions == {
            Permission.ASSISTANTS,
            Permission.APPS,
            Permission.ADMIN,
            Permission.INSIGHTS,
        }

    def test_overlapping_permissions_are_deduplicated(self):
        role1 = RoleInDB(
            id=uuid4(),
            name="role1",
            permissions=[Permission.ASSISTANTS, Permission.ADMIN],
            tenant_id=_TEST_TENANT.id,
        )
        role2 = RoleInDB(
            id=uuid4(),
            name="role2",
            permissions=[Permission.ADMIN, Permission.INSIGHTS],
            tenant_id=_TEST_TENANT.id,
        )
        user = _make_user_with_roles(role1, role2)
        assert user.permissions == {
            Permission.ASSISTANTS,
            Permission.ADMIN,
            Permission.INSIGHTS,
        }


# --- Permission semantics ---


class TestPermissionSemantics:
    """Document and verify expected behavior of the permissions system."""

    def test_all_expected_permissions_exist(self):
        """Ensure all expected permissions are defined in the enum."""
        expected = {
            "assistants",
            "group_chats",
            "apps",
            "services",
            "collections",
            "insights",
            "AI",
            "editor",
            "admin",
            "websites",
            "integrations",
            "shared_spaces",
            "api_keys",
        }
        actual = {p.value for p in Permission}
        assert actual == expected

    def test_admin_does_not_grant_spaces(self):
        """admin permission should NOT implicitly grant spaces access."""
        user = _make_user(Permission.ADMIN)
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.SHARED_SPACES)

    def test_admin_does_not_grant_assistants(self):
        """admin permission should NOT implicitly grant assistants access."""
        user = _make_user(Permission.ADMIN)
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.ASSISTANTS)

    def test_spaces_does_not_grant_admin(self):
        """spaces permission should NOT grant admin access."""
        user = _make_user(Permission.SHARED_SPACES)
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.ADMIN)


# --- Template validation ---


class TestRoleTemplates:
    """Verify predefined role templates have expected permissions."""

    @pytest.fixture
    def templates(self):
        from intric.server.dependencies.predefined_roles import (
            load_predefined_roles_from_config,
        )

        return {
            t["name"]: set(t["permissions"])
            for t in load_predefined_roles_from_config()
        }

    def test_owner_has_all_permissions(self, templates):
        """Owner template should include all permissions."""
        owner = templates["Owner"]
        for p in Permission:
            # Editor is a space-level concept, not expected in Owner template
            if p == Permission.EDITOR:
                continue
            assert p.value in owner, f"Owner template missing permission: {p.value}"

    def test_user_has_basic_permissions(self, templates):
        user = templates["User"]
        assert "assistants" in user
        assert "shared_spaces" in user
        assert "collections" in user
        assert "admin" not in user
        assert "insights" not in user

    def test_ai_configurator_has_ai_permissions(self, templates):
        ai = templates["AI Configurator"]
        assert "AI" in ai
        assert "assistants" in ai
        assert "shared_spaces" in ai
        assert "admin" not in ai

    def test_all_templates_have_spaces(self, templates):
        """All templates should have spaces permission (current expected behavior)."""
        for name, perms in templates.items():
            assert "shared_spaces" in perms, (
                f"Template '{name}' missing shared_spaces permission"
            )
