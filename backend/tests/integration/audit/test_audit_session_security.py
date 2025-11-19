"""Integration tests for audit session security improvements."""

import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import redis.exceptions

from intric.audit.domain.action_types import ActionType
from intric.audit.infrastructure.audit_session_service import AuditSessionService


@pytest.mark.asyncio
async def test_environment_aware_cookies_in_development(client, auth_headers, monkeypatch):
    """Test that cookies use relaxed settings in development/testing mode."""
    # Create audit access session
    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "security_incident",
            "description": "Testing cookie settings in dev environment"
        },
        headers=auth_headers
    )

    assert response.status_code == 200
    assert "audit_session_id" in response.cookies

    # Verify cookie settings for dev/test environment
    cookie = response.cookies["audit_session_id"]
    # In test mode, secure should be False and samesite should be "lax"
    assert cookie.get("secure") is None or cookie.get("secure") == False
    assert cookie.get("samesite") == "lax" or cookie.get("samesite") is None
    assert cookie.get("httponly") is True
    assert cookie.get("path") == "/api/v1"


@pytest.mark.asyncio
async def test_redis_error_handling_on_session_creation(client, auth_headers):
    """Test that Redis errors return 503 with helpful message."""
    with patch("intric.audit.infrastructure.audit_session_service.get_redis") as mock_redis:
        # Simulate Redis connection failure
        mock_redis_instance = AsyncMock()
        mock_redis_instance.setex.side_effect = redis.exceptions.ConnectionError("Redis unavailable")
        mock_redis.return_value = mock_redis_instance

        response = await client.post(
            "/api/v1/audit/access-session",
            json={
                "category": "compliance_audit",
                "description": "Testing Redis error handling for session creation"
            },
            headers=auth_headers
        )

        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_redis_error_handling_on_session_validation(client, auth_headers):
    """Test that Redis errors during validation return 503."""
    # First create a session successfully
    create_response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "investigation",
            "description": "Testing Redis error handling during validation"
        },
        headers=auth_headers
    )
    assert create_response.status_code == 200

    # Now simulate Redis failure on validation
    with patch("intric.audit.infrastructure.audit_session_service.get_redis") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.get.side_effect = redis.exceptions.TimeoutError("Redis timeout")
        mock_redis.return_value = mock_redis_instance

        response = await client.get(
            "/api/v1/audit/logs",
            headers=auth_headers,
            cookies=create_response.cookies
        )

        assert response.status_code == 503


@pytest.mark.asyncio
async def test_rate_limiting_enforces_5_sessions_per_hour(client, auth_headers):
    """Test that rate limiting blocks the 6th session creation attempt."""
    # Create 5 sessions (should all succeed)
    for i in range(5):
        response = await client.post(
            "/api/v1/audit/access-session",
            json={
                "category": f"test_category_{i}",
                "description": f"Testing rate limiting - attempt {i + 1}"
            },
            headers=auth_headers
        )
        assert response.status_code == 200, f"Session {i + 1} should succeed"

    # 6th attempt should be rate limited
    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "test_category_6",
            "description": "Testing rate limiting - attempt 6 (should fail)"
        },
        headers=auth_headers
    )

    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()
    assert "5" in response.json()["detail"]


@pytest.mark.asyncio
async def test_session_creation_is_audit_logged(client, auth_headers, db_session, test_tenant):
    """Test that session creation events are logged to audit logs."""
    # Create audit access session
    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "security_incident",
            "description": "Testing that session creation is audit logged"
        },
        headers=auth_headers
    )

    assert response.status_code == 200
    session_id = response.cookies["audit_session_id"]

    # Query audit logs to verify the session creation was logged
    async with db_session() as session:
        from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
        from intric.audit.application.audit_service import AuditService

        repo = AuditLogRepositoryImpl(session)
        service = AuditService(repo)

        logs, count = await service.get_logs(
            tenant_id=test_tenant.id,
            action=ActionType.AUDIT_SESSION_CREATED,
            page=1,
            page_size=10
        )

        assert count > 0, "Session creation should be audit logged"
        assert any(log.action == ActionType.AUDIT_SESSION_CREATED for log in logs)

        # Verify metadata contains session details
        session_log = next(log for log in logs if log.action == ActionType.AUDIT_SESSION_CREATED)
        assert "session_id" in session_log.metadata
        assert session_log.metadata["justification"]["category"] == "security_incident"
        assert "rate_limit" in session_log.metadata


@pytest.mark.asyncio
async def test_session_extension_on_active_use(client, auth_headers):
    """Test that active users' sessions are extended automatically."""
    # Create audit access session
    create_response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "compliance_audit",
            "description": "Testing session extension on active use"
        },
        headers=auth_headers
    )

    assert create_response.status_code == 200
    cookies = create_response.cookies

    # Mock Redis to track extend_session calls
    with patch.object(AuditSessionService, "extend_session") as mock_extend:
        mock_extend.return_value = True

        # Access audit logs (should trigger session extension)
        response = await client.get(
            "/api/v1/audit/logs",
            headers=auth_headers,
            cookies=cookies
        )

        assert response.status_code == 200
        # Verify that extend_session was called
        mock_extend.assert_called_once()


@pytest.mark.asyncio
async def test_tenant_isolation_in_sessions(client, auth_headers, test_user_2, test_tenant_2):
    """Test that sessions are properly isolated by tenant."""
    # User 1 creates a session
    user1_response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "investigation",
            "description": "Testing tenant isolation in sessions"
        },
        headers=auth_headers
    )

    assert user1_response.status_code == 200
    user1_session_cookie = user1_response.cookies

    # User 2 (different tenant) tries to use user 1's session
    # This should fail due to tenant isolation validation
    auth_headers_user2 = {
        "Authorization": f"Bearer {test_user_2.token}"  # Different tenant
    }

    response = await client.get(
        "/api/v1/audit/logs",
        headers=auth_headers_user2,
        cookies=user1_session_cookie  # Using user 1's session cookie
    )

    # Should be rejected due to tenant mismatch
    assert response.status_code == 403
    assert "invalid or expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_session_expiration_returns_403(client, auth_headers):
    """Test that expired sessions return 403 error."""
    # Create session
    create_response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "compliance_audit",
            "description": "Testing session expiration behavior"
        },
        headers=auth_headers
    )

    assert create_response.status_code == 200

    # Simulate expired session by clearing Redis
    with patch.object(AuditSessionService, "validate_session") as mock_validate:
        mock_validate.return_value = None  # Session expired/not found

        response = await client.get(
            "/api/v1/audit/logs",
            headers=auth_headers,
            cookies=create_response.cookies
        )

        assert response.status_code == 403
        assert "invalid or expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_missing_session_cookie_returns_403(client, auth_headers):
    """Test that requests without session cookie are rejected."""
    response = await client.get(
        "/api/v1/audit/logs",
        headers=auth_headers
        # No cookies provided
    )

    assert response.status_code == 403
    assert "requires justification" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dependency_injection_for_audit_session_service(container):
    """Test that AuditSessionService is properly injected via container."""
    # Verify service can be retrieved from container
    service = container.audit_session_service()

    assert service is not None
    assert isinstance(service, AuditSessionService)
    assert hasattr(service, "create_session")
    assert hasattr(service, "validate_session")
    assert hasattr(service, "extend_session")
    assert hasattr(service, "revoke_session")
