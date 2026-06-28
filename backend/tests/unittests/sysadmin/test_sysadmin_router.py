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

from eneo.main.exceptions import NotFoundException
from eneo.scim.services.token_service import ScimTokenService
from eneo.sysadmin.sysadmin_router import (
    create_scim_token,
    delete_scim_token,
    delete_user,
    get_access_token,
    get_scim_token_status,
    get_user,
    update_user,
)
from eneo.users.user import UserUpdatePublic


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


# ---------------------------------------------------------------------------
# SCIM token endpoints
# ---------------------------------------------------------------------------


def _scim_session():
    """Session mock that supports `async with session.begin():` (transaction
    control only — DB access is mocked at the repository layer below)."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.begin = MagicMock(return_value=cm)
    return session


def _scim_container(repo, audit=None):
    audit = audit or AsyncMock()
    container = MagicMock()
    container.session.return_value = _scim_session()
    container.scim_token_service.return_value = ScimTokenService(
        repository=repo, audit_service=audit
    )
    return container, audit


class TestCreateScimToken:
    async def test_returns_token_for_existing_tenant(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.tenant_exists.return_value = True
        container, _ = _scim_container(repo)

        result = await create_scim_token(tenant_id=tenant_id, container=container)

        assert result.tenant_id == tenant_id
        assert isinstance(result.token, str) and len(result.token) > 0

    async def test_writes_to_db_and_logs_audit(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.tenant_exists.return_value = True
        container, audit = _scim_container(repo)

        await create_scim_token(tenant_id=tenant_id, container=container)

        repo.set_token_hash.assert_awaited_once()
        audit.log.assert_called_once()

    async def test_raises_404_for_unknown_tenant(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.tenant_exists.return_value = False
        container, _ = _scim_container(repo)

        with pytest.raises(NotFoundException):
            await create_scim_token(tenant_id=tenant_id, container=container)


class TestGetScimTokenStatus:
    async def test_returns_active_when_hash_present(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.get_token_hash.return_value = (True, "abc123hash")
        container, _ = _scim_container(repo)

        status = await get_scim_token_status(tenant_id=tenant_id, container=container)

        assert status.tenant_id == tenant_id
        assert status.is_active is True

    async def test_returns_inactive_when_no_hash(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.get_token_hash.return_value = (True, None)
        container, _ = _scim_container(repo)

        status = await get_scim_token_status(tenant_id=tenant_id, container=container)

        assert status.is_active is False

    async def test_raises_404_for_unknown_tenant(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.get_token_hash.return_value = (False, None)
        container, _ = _scim_container(repo)

        with pytest.raises(NotFoundException):
            await get_scim_token_status(tenant_id=tenant_id, container=container)


class TestDeleteScimToken:
    async def test_revokes_token_for_existing_tenant(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.tenant_exists.return_value = True
        container, audit = _scim_container(repo)

        result = await delete_scim_token(tenant_id=tenant_id, container=container)

        assert result is None
        repo.set_token_hash.assert_awaited_once_with(tenant_id, None)
        audit.log.assert_called_once()

    async def test_raises_404_for_unknown_tenant(self):
        tenant_id = uuid.uuid4()
        repo = AsyncMock()
        repo.tenant_exists.return_value = False
        container, _ = _scim_container(repo)

        with pytest.raises(NotFoundException):
            await delete_scim_token(tenant_id=tenant_id, container=container)
