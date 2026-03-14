# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""
Unit tests for sysadmin router endpoints.

These tests ensure proper error handling and service layer usage
in the sysadmin endpoints.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.allowed_origins.allowed_origin_models import AllowedOriginCreate
from intric.main.exceptions import NotFoundException
from intric.sysadmin.sysadmin_router import (
    add_origin,
    delete_origin as delete_allowed_origin,
    get_access_token,
    delete_user,
    get_user,
    update_user,
)
from intric.users.user import UserUpdatePublic


@pytest.fixture
def mock_container():
    """Create a mock container with common services."""
    container = MagicMock()
    container.user_service.return_value = AsyncMock()
    container.auth_service.return_value = MagicMock()
    container.audit_service.return_value = AsyncMock()
    return container


@pytest.fixture
def mock_user():
    """Create a mock user object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.username = "testuser"
    user.tenant_id = uuid.uuid4()
    return user


class TestGetAccessToken:
    """Tests for the /users/{user_id}/access-token/ endpoint."""

    async def test_returns_access_token_for_valid_user(self, mock_container, mock_user):
        """Should return JWT token when user exists."""
        user_service = mock_container.user_service.return_value
        auth_service = mock_container.auth_service.return_value

        user_service.get_user.return_value = mock_user
        auth_service.create_access_token_for_user.return_value = "jwt_token_123"

        result = await get_access_token(user_id=mock_user.id, container=mock_container)

        user_service.get_user.assert_called_once_with(mock_user.id)
        auth_service.create_access_token_for_user.assert_called_once_with(mock_user)
        assert result == "jwt_token_123"

    async def test_raises_not_found_for_nonexistent_user(self, mock_container):
        """Should raise NotFoundException when user doesn't exist."""
        user_service = mock_container.user_service.return_value
        user_service.get_user.side_effect = NotFoundException("No such user exists.")

        nonexistent_id = uuid.uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await get_access_token(user_id=nonexistent_id, container=mock_container)

        assert "No such user exists" in str(exc_info.value)
        user_service.get_user.assert_called_once_with(nonexistent_id)


class TestGetUser:
    """Tests for the GET /users/{user_id}/ endpoint."""

    async def test_returns_user_when_exists(self, mock_container, mock_user):
        """Should return user when found."""
        user_service = mock_container.user_service.return_value
        user_service.get_user.return_value = mock_user

        result = await get_user(user_id=mock_user.id, container=mock_container)

        user_service.get_user.assert_called_once_with(mock_user.id)
        assert result == mock_user

    async def test_raises_not_found_for_nonexistent_user(self, mock_container):
        """Should raise NotFoundException when user doesn't exist."""
        user_service = mock_container.user_service.return_value
        user_service.get_user.side_effect = NotFoundException("No such user exists.")

        nonexistent_id = uuid.uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await get_user(user_id=nonexistent_id, container=mock_container)

        assert "No such user exists" in str(exc_info.value)


class TestDeleteUser:
    """Tests for the DELETE /users/{user_id}/ endpoint."""

    async def test_deletes_user_and_returns_success(self, mock_container, mock_user):
        """Should delete user and return success response."""
        user_service = mock_container.user_service.return_value
        audit_service = mock_container.audit_service.return_value

        user_service.get_user.return_value = mock_user
        user_service.delete_user.return_value = True

        result = await delete_user(user_id=mock_user.id, container=mock_container)

        user_service.get_user.assert_called_once_with(mock_user.id)
        user_service.delete_user.assert_called_once_with(mock_user.id)
        audit_service.log_async.assert_called_once()
        assert result.success is True

    async def test_raises_not_found_for_nonexistent_user(self, mock_container):
        """Should raise NotFoundException when user doesn't exist."""
        user_service = mock_container.user_service.return_value
        user_service.get_user.side_effect = NotFoundException("No such user exists.")

        nonexistent_id = uuid.uuid4()

        with pytest.raises(NotFoundException) as exc_info:
            await delete_user(user_id=nonexistent_id, container=mock_container)

        assert "No such user exists" in str(exc_info.value)
        user_service.delete_user.assert_not_called()


class TestUpdateUser:
    """Tests for the POST /users/{user_id}/ endpoint."""

    async def test_updates_user_and_returns_updated(self, mock_container, mock_user):
        """Should update user and return updated user."""
        user_service = mock_container.user_service.return_value
        audit_service = mock_container.audit_service.return_value

        updated_user = MagicMock()
        updated_user.id = mock_user.id
        updated_user.email = "new@example.com"
        updated_user.username = "newusername"
        updated_user.tenant_id = mock_user.tenant_id

        user_service.get_user.return_value = mock_user
        user_service.update_user.return_value = updated_user

        user_update = UserUpdatePublic(email="new@example.com")

        result = await update_user(
            user_id=mock_user.id,
            user_update=user_update,
            container=mock_container,
        )

        user_service.get_user.assert_called_once_with(mock_user.id)
        user_service.update_user.assert_called_once_with(mock_user.id, user_update)
        audit_service.log_async.assert_called_once()
        assert result == updated_user

    async def test_raises_not_found_for_nonexistent_user(self, mock_container):
        """Should raise NotFoundException when user doesn't exist."""
        user_service = mock_container.user_service.return_value
        user_service.get_user.side_effect = NotFoundException("No such user exists.")

        nonexistent_id = uuid.uuid4()
        user_update = UserUpdatePublic(email="new@example.com")

        with pytest.raises(NotFoundException) as exc_info:
            await update_user(
                user_id=nonexistent_id,
                user_update=user_update,
                container=mock_container,
            )

        assert "No such user exists" in str(exc_info.value)
        user_service.update_user.assert_not_called()


class TestAllowedOriginCacheInvalidation:
    """Allowed-origin mutations should invalidate API-key origin cache immediately."""

    async def test_add_origin_builds_policy_service_without_user_dependency(self, monkeypatch):
        tenant_id = uuid.uuid4()
        origin = AllowedOriginCreate(
            url="https://app.example.com",
            tenant_id=tenant_id,
        )

        container = MagicMock()
        allowed_origin_repo = AsyncMock()
        allowed_origin_repo.add_origin = AsyncMock(
            return_value=MagicMock(url=origin.url, tenant_id=tenant_id)
        )
        container.allowed_origin_repo.return_value = allowed_origin_repo
        container.audit_service.return_value = AsyncMock(log_async=AsyncMock())

        captured_kwargs = {}
        policy_service = MagicMock()

        class _PolicyService:
            def __init__(self, **kwargs):
                nonlocal captured_kwargs
                captured_kwargs = kwargs

            def invalidate_tenant_origin_cache(self, tenant_id: uuid.UUID):
                policy_service.invalidate_tenant_origin_cache(tenant_id)

        monkeypatch.setattr(
            "intric.sysadmin.sysadmin_router.ApiKeyPolicyService",
            _PolicyService,
        )

        await add_origin(origin=origin, container=container)

        assert captured_kwargs["allowed_origin_repo"] is container.allowed_origin_repo.return_value
        assert captured_kwargs["space_service"] is None
        assert captured_kwargs["user"] is None
        policy_service.invalidate_tenant_origin_cache.assert_called_once_with(tenant_id)

    async def test_add_origin_invalidates_api_key_origin_cache(self, monkeypatch):
        tenant_id = uuid.uuid4()
        origin = AllowedOriginCreate(
            url="https://app.example.com",
            tenant_id=tenant_id,
        )

        container = MagicMock()
        allowed_origin_repo = AsyncMock()
        allowed_origin_repo.add_origin = AsyncMock(
            return_value=MagicMock(url=origin.url, tenant_id=tenant_id)
        )
        container.allowed_origin_repo.return_value = allowed_origin_repo
        container.audit_service.return_value = AsyncMock(log_async=AsyncMock())
        policy_service = MagicMock()
        monkeypatch.setattr(
            "intric.sysadmin.sysadmin_router.ApiKeyPolicyService",
            MagicMock(return_value=policy_service),
        )

        await add_origin(origin=origin, container=container)

        policy_service.invalidate_tenant_origin_cache.assert_called_once_with(tenant_id)

    async def test_delete_origin_invalidates_api_key_origin_cache(self, monkeypatch):
        tenant_id = uuid.uuid4()
        origin_id = uuid.uuid4()

        container = MagicMock()
        allowed_origin_repo = AsyncMock()
        allowed_origin_repo.get_by_id = AsyncMock(
            return_value=MagicMock(
                id=origin_id,
                url="https://app.example.com",
                tenant_id=tenant_id,
            )
        )
        allowed_origin_repo.delete = AsyncMock(return_value=None)
        container.allowed_origin_repo.return_value = allowed_origin_repo
        container.audit_service.return_value = AsyncMock(log_async=AsyncMock())
        policy_service = MagicMock()
        monkeypatch.setattr(
            "intric.sysadmin.sysadmin_router.ApiKeyPolicyService",
            MagicMock(return_value=policy_service),
        )

        await delete_allowed_origin(id=origin_id, container=container)

        policy_service.invalidate_tenant_origin_cache.assert_called_once_with(tenant_id)

    async def test_delete_origin_missing_record_does_not_invalidate_cache(self, monkeypatch):
        origin_id = uuid.uuid4()

        container = MagicMock()
        allowed_origin_repo = AsyncMock()
        allowed_origin_repo.get_by_id = AsyncMock(return_value=None)
        allowed_origin_repo.delete = AsyncMock(return_value=None)
        container.allowed_origin_repo.return_value = allowed_origin_repo
        container.audit_service.return_value = AsyncMock(log_async=AsyncMock())
        policy_service = MagicMock()
        monkeypatch.setattr(
            "intric.sysadmin.sysadmin_router.ApiKeyPolicyService",
            MagicMock(return_value=policy_service),
        )

        await delete_allowed_origin(id=origin_id, container=container)

        policy_service.invalidate_tenant_origin_cache.assert_not_called()
