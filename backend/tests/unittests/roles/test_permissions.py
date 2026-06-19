"""Comprehensive tests for the permissions system."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import (
    Permission,
    has_permission,
    validate_permission,
    validate_permissions,
)
from intric.roles.role import RoleCreateRequest, RoleInDB, RoleUpdateRequest
from intric.roles.roles_service import RolesService
from intric.tenants.tenant import TenantInDB
from intric.users.user import UserInDB

_TEST_TENANT = TenantInDB(id=uuid4(), name="test", quota_limit=1024**3)


def _make_user(*permissions: Permission) -> UserInDB:
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


class MockService:
    def __init__(self, user: UserInDB):
        self.user = user

    @validate_permissions(Permission.ADMIN)
    async def func_in_need_of_validation(self, *args, **kwargs):
        1 / 0


class MockFlowService:
    def __init__(self, user: UserInDB):
        self.user = user

    @validate_permissions(Permission.FLOWS_MANAGE)
    async def manage_flow(self):
        return "ok"


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


async def test_validation_decorator_accepts_legacy_flows_permission_for_granular_flow_guard():
    service = MockFlowService(_make_user(Permission.FLOWS))

    assert await service.manage_flow() == "ok"


async def test_roles_service_does_not_expose_legacy_flows_alias_as_grantable_permission():
    service = RolesService(user=_make_user(Permission.ADMIN), repo=MagicMock())

    permissions = await service.get_permissions()

    assert Permission.FLOWS not in {permission.name for permission in permissions}
    assert Permission.FLOWS_VIEW in {permission.name for permission in permissions}


async def test_roles_service_rejects_legacy_flows_alias_on_create():
    service = RolesService(user=_make_user(Permission.ADMIN), repo=AsyncMock())

    with pytest.raises(BadRequestException, match="legacy 'flows' permission"):
        await service.create_role(
            RoleCreateRequest(name="legacy", permissions=[Permission.FLOWS])
        )


async def test_roles_service_rejects_legacy_flows_alias_on_update():
    role = RoleInDB(
        id=uuid4(),
        name="existing",
        permissions=[Permission.FLOWS_VIEW],
        tenant_id=_TEST_TENANT.id,
    )
    repo = AsyncMock()
    repo.get_role.return_value = role
    service = RolesService(user=_make_user(Permission.ADMIN), repo=repo)

    with pytest.raises(BadRequestException, match="legacy 'flows' permission"):
        await service.update_role(
            RoleUpdateRequest(permissions=[Permission.FLOWS]),
            role.id,
        )


def test_flow_granular_permissions_accept_legacy_flows_permission():
    permissions = [Permission.FLOWS]

    assert has_permission(permissions, Permission.FLOWS_VIEW) is True
    assert has_permission(permissions, Permission.FLOWS_RUN) is True
    assert has_permission(permissions, Permission.FLOWS_MANAGE) is True
    assert has_permission(permissions, Permission.FLOWS_AI_BUILDER) is True
    assert has_permission(permissions, Permission.FLOWS_TRACE) is True


def test_flow_run_permission_grants_view_but_not_manage():
    permissions = [Permission.FLOWS_RUN]

    assert has_permission(permissions, Permission.FLOWS_VIEW) is True
    assert has_permission(permissions, Permission.FLOWS_RUN) is True
    assert has_permission(permissions, Permission.FLOWS_MANAGE) is False


def test_legacy_flows_permission_is_not_implied_by_granular_permissions():
    permissions = [Permission.FLOWS_VIEW, Permission.FLOWS_RUN, Permission.FLOWS_MANAGE]

    assert has_permission(permissions, Permission.FLOWS) is False


def test_validate_permission_rejects_user_without_required_granular_flow_permission():
    user = MagicMock(permissions=[Permission.FLOWS_VIEW])

    with pytest.raises(
        UnauthorizedException,
        match=f"Need permission {Permission.FLOWS_MANAGE.value} in order to access",
    ):
        validate_permission(user, Permission.FLOWS_MANAGE)


class TestValidatePermission:
    @pytest.mark.parametrize("permission", list(Permission))
    def test_user_with_permission_passes(self, permission: Permission):
        user = _make_user(permission)
        validate_permission(user, permission)

    @pytest.mark.parametrize("permission", list(Permission))
    def test_user_without_permission_fails(self, permission: Permission):
        user = _make_user()
        with pytest.raises(UnauthorizedException):
            validate_permission(user, permission)


class TestPermissionsAreIndependent:
    @pytest.mark.parametrize("granted", list(Permission))
    def test_single_permission_does_not_grant_unrelated_permissions(
        self, granted: Permission
    ):
        user = _make_user(granted)
        for other in Permission:
            allowed = other == granted or has_permission([granted], other)
            if allowed:
                validate_permission(user, other)
            else:
                with pytest.raises(UnauthorizedException):
                    validate_permission(user, other)


class TestUserPermissionsAggregation:
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


class TestPermissionSemantics:
    def test_all_expected_permissions_exist(self):
        expected = {
            "assistants",
            "personal_chat",
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
            "flows",
            "flows_view",
            "flows_run",
            "flows_manage",
            "flows_ai_builder",
            "flows_trace",
        }
        actual = {p.value for p in Permission}
        assert actual == expected

    def test_admin_does_not_grant_spaces(self):
        user = _make_user(Permission.ADMIN)
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.SHARED_SPACES)

    def test_admin_does_not_grant_assistants(self):
        user = _make_user(Permission.ADMIN)
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.ASSISTANTS)

    def test_spaces_does_not_grant_admin(self):
        user = _make_user(Permission.SHARED_SPACES)
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.ADMIN)


class TestRoleTemplates:
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
        owner = templates["Owner"]
        for permission in Permission:
            if permission in {Permission.EDITOR, Permission.FLOWS}:
                continue
            assert permission.value in owner, (
                f"Owner template missing permission: {permission.value}"
            )

    def test_user_has_basic_permissions(self, templates):
        user = templates["User"]
        assert "personal_chat" in user
        assert "assistants" in user
        assert "shared_spaces" in user
        assert "collections" in user
        assert "admin" not in user
        assert "insights" not in user
        assert "flows_view" not in user

    def test_ai_configurator_has_ai_permissions(self, templates):
        ai = templates["AI Configurator"]
        assert "AI" in ai
        assert "assistants" in ai
        assert "shared_spaces" in ai
        assert "flows_trace" in ai
        assert "admin" not in ai

    def test_all_templates_have_spaces(self, templates):
        for name, perms in templates.items():
            assert "shared_spaces" in perms, (
                f"Template '{name}' missing shared_spaces permission"
            )
