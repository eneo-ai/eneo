"""Unit tests for AuditSessionService - Redis-based session management."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

import redis.exceptions
from fastapi import HTTPException

from intric.audit.infrastructure.audit_session_service import AuditSessionService


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.setex = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock()
    redis.expire = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def session_service(mock_redis):
    """Create AuditSessionService with mocked Redis."""
    with patch("intric.audit.infrastructure.audit_session_service.get_redis", return_value=mock_redis):
        service = AuditSessionService()
        return service


class TestSessionServiceInit:
    """Tests for service initialization."""

    def test_ttl_is_one_hour(self, session_service):
        """Verify default TTL is 3600 seconds (1 hour)."""
        assert session_service.ttl_seconds == 3600

    def test_service_uses_redis(self, session_service, mock_redis):
        """Verify service uses Redis client."""
        assert session_service.redis is mock_redis


class TestCreateSession:
    """Tests for create_session() method."""

    async def test_create_session_returns_uuid_string(self, session_service):
        """Verify create_session returns a valid UUID string."""
        user_id = uuid4()
        tenant_id = uuid4()

        session_id = await session_service.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            category="investigation",
            description="Test session creation",
        )

        # Verify it's a valid UUID string
        assert isinstance(session_id, str)
        assert len(session_id) == 36  # UUID format with hyphens

    async def test_create_session_stores_in_redis(self, session_service, mock_redis):
        """Verify session data is stored in Redis with correct TTL."""
        user_id = uuid4()
        tenant_id = uuid4()

        await session_service.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            category="compliance",
            description="Compliance audit review",
        )

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args

        # Verify TTL
        assert call_args[0][1] == 3600

        # Verify key format
        key = call_args[0][0]
        assert key.startswith("audit_session:")

    async def test_create_session_stores_correct_data(self, session_service, mock_redis):
        """Verify session data contains all required fields."""
        user_id = uuid4()
        tenant_id = uuid4()

        await session_service.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            category="security_incident",
            description="Investigating suspicious activity",
        )

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])

        assert stored_data["user_id"] == str(user_id)
        assert stored_data["tenant_id"] == str(tenant_id)
        assert stored_data["category"] == "security_incident"
        assert stored_data["description"] == "Investigating suspicious activity"
        assert "created_at" in stored_data

    async def test_create_session_created_at_is_utc_iso(self, session_service, mock_redis):
        """Verify created_at timestamp is ISO format with UTC timezone."""
        user_id = uuid4()
        tenant_id = uuid4()

        await session_service.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            category="test",
            description="Testing timestamp format",
        )

        call_args = mock_redis.setex.call_args
        stored_data = json.loads(call_args[0][2])

        # Should be parseable as ISO format
        created_at = datetime.fromisoformat(stored_data["created_at"])
        assert created_at.tzinfo is not None  # Has timezone info

    async def test_create_session_redis_error_raises_503(self, session_service, mock_redis):
        """Verify Redis error raises 503 Service Unavailable."""
        mock_redis.setex.side_effect = redis.exceptions.RedisError("Connection refused")

        with pytest.raises(HTTPException) as exc_info:
            await session_service.create_session(
                user_id=uuid4(),
                tenant_id=uuid4(),
                category="test",
                description="Should fail",
            )

        assert exc_info.value.status_code == 503
        assert "temporarily unavailable" in exc_info.value.detail.lower()


class TestGetSession:
    """Tests for get_session() method."""

    async def test_get_session_returns_data_when_exists(self, session_service, mock_redis):
        """Verify get_session returns parsed data when session exists."""
        session_data = {
            "user_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "category": "investigation",
            "description": "Test session",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(session_data).encode("utf-8")

        result = await session_service.get_session("test-session-id")

        assert result == session_data

    async def test_get_session_returns_none_when_not_exists(self, session_service, mock_redis):
        """Verify get_session returns None for non-existent session."""
        mock_redis.get.return_value = None

        result = await session_service.get_session("nonexistent-session")

        assert result is None

    async def test_get_session_returns_none_when_expired(self, session_service, mock_redis):
        """Verify get_session returns None for expired session (Redis auto-deletes)."""
        mock_redis.get.return_value = None  # Redis returns None for expired keys

        result = await session_service.get_session("expired-session")

        assert result is None

    async def test_get_session_uses_correct_key_format(self, session_service, mock_redis):
        """Verify get_session uses audit_session:{id} key format."""
        session_id = "test-session-123"
        mock_redis.get.return_value = None

        await session_service.get_session(session_id)

        mock_redis.get.assert_called_once_with(f"audit_session:{session_id}")

    async def test_get_session_redis_error_raises_503(self, session_service, mock_redis):
        """Verify Redis error raises 503 Service Unavailable."""
        mock_redis.get.side_effect = redis.exceptions.RedisError("Timeout")

        with pytest.raises(HTTPException) as exc_info:
            await session_service.get_session("test-session")

        assert exc_info.value.status_code == 503


class TestValidateSession:
    """Tests for validate_session() - security-critical validation."""

    async def test_validate_session_returns_data_when_valid(self, session_service, mock_redis):
        """Verify valid session returns session data."""
        user_id = uuid4()
        tenant_id = uuid4()
        session_data = {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "category": "test",
            "description": "Valid session",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(session_data).encode("utf-8")

        result = await session_service.validate_session(
            session_id="test-session",
            user_id=user_id,
            tenant_id=tenant_id,
        )

        assert result == session_data

    async def test_validate_session_returns_none_when_session_missing(self, session_service, mock_redis):
        """Verify missing session returns None."""
        mock_redis.get.return_value = None

        result = await session_service.validate_session(
            session_id="nonexistent",
            user_id=uuid4(),
            tenant_id=uuid4(),
        )

        assert result is None

    async def test_validate_session_returns_none_when_user_mismatch(self, session_service, mock_redis):
        """Verify user ID mismatch returns None (security)."""
        session_user = uuid4()
        different_user = uuid4()
        tenant_id = uuid4()

        session_data = {
            "user_id": str(session_user),
            "tenant_id": str(tenant_id),
            "category": "test",
            "description": "Test",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(session_data).encode("utf-8")

        result = await session_service.validate_session(
            session_id="test-session",
            user_id=different_user,  # Different user!
            tenant_id=tenant_id,
        )

        assert result is None  # Rejected due to user mismatch

    async def test_validate_session_returns_none_when_tenant_mismatch(self, session_service, mock_redis):
        """Verify tenant ID mismatch returns None (tenant isolation)."""
        user_id = uuid4()
        session_tenant = uuid4()
        different_tenant = uuid4()

        session_data = {
            "user_id": str(user_id),
            "tenant_id": str(session_tenant),
            "category": "test",
            "description": "Test",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(session_data).encode("utf-8")

        result = await session_service.validate_session(
            session_id="test-session",
            user_id=user_id,
            tenant_id=different_tenant,  # Different tenant!
        )

        assert result is None  # Rejected due to tenant mismatch

    async def test_validate_session_uses_constant_time_comparison(self, session_service, mock_redis):
        """Verify validation uses secrets.compare_digest for timing attack prevention."""
        # This test verifies the implementation uses constant-time comparison
        # by checking that the code imports and uses secrets.compare_digest
        import secrets

        user_id = uuid4()
        tenant_id = uuid4()
        session_data = {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "category": "test",
            "description": "Test",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        mock_redis.get.return_value = json.dumps(session_data).encode("utf-8")

        # Patch secrets.compare_digest to verify it's being called
        with patch("intric.audit.infrastructure.audit_session_service.secrets.compare_digest") as mock_compare:
            mock_compare.return_value = True

            await session_service.validate_session(
                session_id="test-session",
                user_id=user_id,
                tenant_id=tenant_id,
            )

            # Verify compare_digest was called (for timing attack prevention)
            assert mock_compare.call_count == 2  # Once for user_id, once for tenant_id


class TestRevokeSession:
    """Tests for revoke_session() method."""

    async def test_revoke_session_deletes_from_redis(self, session_service, mock_redis):
        """Verify revoke_session deletes the session key."""
        session_id = "session-to-revoke"

        await session_service.revoke_session(session_id)

        mock_redis.delete.assert_called_once_with(f"audit_session:{session_id}")

    async def test_revoke_session_succeeds_even_if_missing(self, session_service, mock_redis):
        """Verify revoking non-existent session doesn't raise error."""
        mock_redis.delete.return_value = 0  # Redis returns 0 when key doesn't exist

        # Should not raise
        await session_service.revoke_session("nonexistent-session")

    async def test_revoke_session_redis_error_raises_503(self, session_service, mock_redis):
        """Verify Redis error raises 503 Service Unavailable."""
        mock_redis.delete.side_effect = redis.exceptions.RedisError("Connection lost")

        with pytest.raises(HTTPException) as exc_info:
            await session_service.revoke_session("test-session")

        assert exc_info.value.status_code == 503


class TestExtendSession:
    """Tests for extend_session() method."""

    async def test_extend_session_returns_true_when_exists(self, session_service, mock_redis):
        """Verify extend_session returns True when session exists."""
        mock_redis.expire.return_value = 1  # Key exists and TTL was updated

        result = await session_service.extend_session("existing-session")

        assert result is True

    async def test_extend_session_returns_false_when_missing(self, session_service, mock_redis):
        """Verify extend_session returns False when session doesn't exist."""
        mock_redis.expire.return_value = 0  # Key doesn't exist

        result = await session_service.extend_session("nonexistent-session")

        assert result is False

    async def test_extend_session_uses_correct_ttl(self, session_service, mock_redis):
        """Verify extend_session uses 1 hour TTL."""
        await session_service.extend_session("test-session")

        mock_redis.expire.assert_called_once()
        call_args = mock_redis.expire.call_args
        assert call_args[0][1] == 3600  # 1 hour

    async def test_extend_session_uses_atomic_expire(self, session_service, mock_redis):
        """Verify extend_session uses atomic EXPIRE (not exists-then-expire)."""
        # This is important to avoid race conditions
        await session_service.extend_session("test-session")

        # Only expire should be called, not exists + expire
        mock_redis.expire.assert_called_once()
        mock_redis.exists.assert_not_called() if hasattr(mock_redis, 'exists') else None

    async def test_extend_session_redis_error_raises_503(self, session_service, mock_redis):
        """Verify Redis error raises 503 Service Unavailable."""
        mock_redis.expire.side_effect = redis.exceptions.RedisError("Network error")

        with pytest.raises(HTTPException) as exc_info:
            await session_service.extend_session("test-session")

        assert exc_info.value.status_code == 503


class TestSessionKeyFormat:
    """Tests for Redis key format consistency."""

    async def test_all_methods_use_consistent_key_format(self, session_service, mock_redis):
        """Verify all methods use audit_session:{id} key format."""
        session_id = "test-session-uuid"
        user_id = uuid4()
        tenant_id = uuid4()

        mock_redis.get.return_value = json.dumps({
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "category": "test",
            "description": "Test",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).encode()

        # Test get_session
        await session_service.get_session(session_id)
        mock_redis.get.assert_called_with(f"audit_session:{session_id}")

        # Test revoke_session
        await session_service.revoke_session(session_id)
        mock_redis.delete.assert_called_with(f"audit_session:{session_id}")

        # Test extend_session
        await session_service.extend_session(session_id)
        mock_redis.expire.assert_called()
        assert f"audit_session:{session_id}" in str(mock_redis.expire.call_args)


class TestServiceUnavailableErrors:
    """Tests for 503 Service Unavailable handling across all methods."""

    @pytest.mark.parametrize("exception_class", [
        redis.exceptions.ConnectionError,
        redis.exceptions.TimeoutError,
        redis.exceptions.RedisError,
    ])
    async def test_create_session_handles_redis_exceptions(self, session_service, mock_redis, exception_class):
        """Verify create_session handles various Redis exceptions."""
        mock_redis.setex.side_effect = exception_class("Test error")

        with pytest.raises(HTTPException) as exc_info:
            await session_service.create_session(
                user_id=uuid4(),
                tenant_id=uuid4(),
                category="test",
                description="Test description",
            )

        assert exc_info.value.status_code == 503

    @pytest.mark.parametrize("exception_class", [
        redis.exceptions.ConnectionError,
        redis.exceptions.TimeoutError,
        redis.exceptions.RedisError,
    ])
    async def test_get_session_handles_redis_exceptions(self, session_service, mock_redis, exception_class):
        """Verify get_session handles various Redis exceptions."""
        mock_redis.get.side_effect = exception_class("Test error")

        with pytest.raises(HTTPException) as exc_info:
            await session_service.get_session("test-session")

        assert exc_info.value.status_code == 503
