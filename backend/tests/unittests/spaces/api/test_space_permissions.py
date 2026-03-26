"""Tests for spaces permission checks.

Verifies that:
- Creating shared spaces requires the 'spaces' permission
- Updating shared spaces requires the 'spaces' permission
- Deleting shared spaces requires the 'spaces' permission
- Personal space operations are NOT blocked by missing 'spaces' permission
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission, validate_permission
from intric.roles.role import RoleInDB
from intric.spaces.api import space_router
from intric.users.user import UserInDB
from tests.fixtures import TEST_TENANT


def _make_user(permissions: list[Permission]) -> UserInDB:
    role = RoleInDB(
        id=uuid4(),
        name="test_role",
        permissions=permissions,
        tenant_id=TEST_TENANT.id,
    )
    return UserInDB(
        id=uuid4(),
        username="testuser",
        email="test@test.com",
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=TEST_TENANT.id,
        tenant=TEST_TENANT,
        roles=[role],
        state="active",
    )


def _make_space(personal: bool = False):
    return SimpleNamespace(
        id=uuid4(),
        name="Test Space",
        is_personal=lambda: personal,
    )


class TestValidateSpacesPermission:
    """Test that validate_permission correctly checks for SPACES."""

    def test_user_with_spaces_permission_passes(self):
        user = _make_user([Permission.SHARED_SPACES])
        # Should not raise
        validate_permission(user, Permission.SHARED_SPACES)

    def test_user_without_spaces_permission_fails(self):
        user = _make_user([Permission.ASSISTANTS])
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.SHARED_SPACES)

    def test_user_with_no_permissions_fails(self):
        user = _make_user([])
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.SHARED_SPACES)

    def test_admin_without_spaces_still_fails(self):
        """admin permission does NOT grant spaces permission."""
        user = _make_user([Permission.ADMIN])
        with pytest.raises(UnauthorizedException):
            validate_permission(user, Permission.SHARED_SPACES)


class TestUpdateSpacePermission:
    """Test that update_space checks spaces permission for shared spaces."""

    @pytest.fixture
    def shared_space(self):
        return _make_space(personal=False)

    @pytest.fixture
    def personal_space(self):
        return _make_space(personal=True)

    async def test_update_shared_space_without_permission_raises(self, shared_space):
        user = _make_user([Permission.ASSISTANTS])  # no SPACES
        service = AsyncMock()
        service.get_space.return_value = shared_space

        container = SimpleNamespace(
            space_service=lambda: service,
            space_assembler=lambda: AsyncMock(),
            user=lambda: user,
            audit_service=lambda: AsyncMock(),
        )

        with pytest.raises(UnauthorizedException):
            await space_router.update_space(
                id=shared_space.id,
                update_space_req=SimpleNamespace(
                    name=None, description=None, embedding_models=None,
                    completion_models=None, transcription_models=None,
                    mcp_servers=None, mcp_tools=None, security_classification=None,
                    data_retention_days=None, icon_id=None,
                    model_dump=lambda exclude_unset: {},
                ),
                container=container,
            )

    async def test_update_personal_space_without_permission_allowed(self, personal_space):
        user = _make_user([Permission.ASSISTANTS])  # no SPACES
        service = AsyncMock()
        service.get_space.return_value = personal_space
        service.update_space.return_value = personal_space

        assembler = AsyncMock()
        assembler.from_space_to_model.return_value = personal_space

        container = SimpleNamespace(
            space_service=lambda: service,
            space_assembler=lambda: assembler,
            user=lambda: user,
            audit_service=lambda: AsyncMock(),
        )

        # Should NOT raise — personal space is exempt
        await space_router.update_space(
            id=personal_space.id,
            update_space_req=SimpleNamespace(
                name=None, description=None, embedding_models=None,
                completion_models=None, transcription_models=None,
                mcp_servers=None, mcp_tools=None, security_classification=None,
                data_retention_days=None, icon_id=None,
                model_dump=lambda exclude_unset: {},
            ),
            container=container,
        )


class TestDeleteSpacePermission:
    """Test that delete_space checks spaces permission for shared spaces."""

    async def test_delete_shared_space_without_permission_raises(self):
        user = _make_user([Permission.ASSISTANTS])  # no SPACES
        shared_space = _make_space(personal=False)
        service = AsyncMock()
        service.get_space.return_value = shared_space

        container = SimpleNamespace(
            space_service=lambda: service,
            user=lambda: user,
            audit_service=lambda: AsyncMock(),
        )

        with pytest.raises(UnauthorizedException):
            await space_router.delete_space(id=shared_space.id, container=container)

    async def test_delete_shared_space_with_permission_proceeds(self):
        user = _make_user([Permission.SHARED_SPACES])
        shared_space = _make_space(personal=False)
        service = AsyncMock()
        service.get_space.return_value = shared_space
        service.delete_space.return_value = None

        container = SimpleNamespace(
            space_service=lambda: service,
            user=lambda: user,
            audit_service=lambda: AsyncMock(),
        )

        # Should NOT raise
        await space_router.delete_space(id=shared_space.id, container=container)
        service.delete_space.assert_awaited_once()

    async def test_delete_personal_space_without_permission_allowed(self):
        user = _make_user([Permission.ASSISTANTS])  # no SPACES
        personal_space = _make_space(personal=True)
        service = AsyncMock()
        service.get_space.return_value = personal_space
        service.delete_space.return_value = None

        container = SimpleNamespace(
            space_service=lambda: service,
            user=lambda: user,
            audit_service=lambda: AsyncMock(),
        )

        # Should NOT raise — personal space is exempt
        await space_router.delete_space(id=personal_space.id, container=container)
        service.delete_space.assert_awaited_once()
