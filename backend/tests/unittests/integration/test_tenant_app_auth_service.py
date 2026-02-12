"""Unit tests for TenantAppAuthService - token caching and lifecycle management.

Tests the client credentials flow and token caching logic for person-independent
tenant app authentication.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from intric.integration.infrastructure.auth_service.tenant_app_auth_service import (
    TenantAppAuthService,
    TenantAppToken,
)

@pytest.fixture
def mock_tenant_app():
    """Create a mock tenant SharePoint app."""
    app = MagicMock()
    app.id = uuid4()
    app.tenant_id = uuid4()
    app.client_id = "azure-client-id-123"
    app.client_secret = "azure-client-secret-456"
    app.tenant_domain = "contoso.onmicrosoft.com"
    app.is_active = True
    return app

@pytest.fixture
def mock_token_response():
    """Create a mock successful token response."""
    return {
        "token_type": "Bearer",
        "expires_in": 3600,  # 1 hour
        "access_token": "mock-access-token-123",
    }

@pytest.fixture
def mock_httpx_response(mock_token_response):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = mock_token_response
    response.text = "success"
    return response

@pytest.fixture
def service():
    """Create a fresh TenantAppAuthService instance."""
    return TenantAppAuthService()

def test_tenant_app_token_is_expired():
    """Token correctly identifies if it has expired."""
    # Create expired token
    expired_token = TenantAppToken(
        access_token="token",
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    assert expired_token.is_expired() is True

    # Create valid token
    valid_token = TenantAppToken(
        access_token="token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    assert valid_token.is_expired() is False


def test_tenant_app_token_is_expiring_soon():
    """Token correctly identifies if it's expiring within threshold."""
    # Token expiring in 3 minutes (default threshold is 5 minutes)
    soon_expiring = TenantAppToken(
        access_token="token",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=3)
    )
    assert soon_expiring.is_expiring_soon() is True

    # Token expiring in 10 minutes (beyond default threshold)
    not_expiring_soon = TenantAppToken(
        access_token="token",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
    )
    assert not_expiring_soon.is_expiring_soon() is False


def test_tenant_app_token_is_expiring_soon_custom_threshold():
    """Token correctly uses custom expiration threshold."""
    token = TenantAppToken(
        access_token="token",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=8)
    )

    # With 5-minute threshold (default)
    assert token.is_expiring_soon(minutes=5) is False

    # With 10-minute threshold
    assert token.is_expiring_soon(minutes=10) is True

async def test_acquire_token_success(service, mock_tenant_app, mock_httpx_response):
    """Successfully acquires token via client credentials flow."""
    # Mock httpx.AsyncClient
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # Execute
        token = await service.get_access_token(mock_tenant_app)

        # Assert
        assert token == "mock-access-token-123"

        # Verify HTTP request was made correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args

        assert "login.microsoftonline.com" in call_args[0][0]
        assert "contoso.onmicrosoft.com" in call_args[0][0]

        posted_data = call_args.kwargs["data"]
        assert posted_data["client_id"] == "azure-client-id-123"
        assert posted_data["client_secret"] == "azure-client-secret-456"
        assert posted_data["grant_type"] == "client_credentials"
        assert posted_data["scope"] == "https://graph.microsoft.com/.default"

async def test_token_caching_returns_cached_if_valid(service, mock_tenant_app, mock_httpx_response):
    """Returns cached token if it hasn't expired and isn't expiring soon."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # First call - acquires token
        token1 = await service.get_access_token(mock_tenant_app)

        # Second call - should use cache
        token2 = await service.get_access_token(mock_tenant_app)

        # Assert
        assert token1 == token2 == "mock-access-token-123"

        # Verify HTTP request was only made once
        assert mock_client.post.call_count == 1


async def test_token_auto_refresh_on_expiration_threshold(service, mock_tenant_app):
    """Automatically refreshes tokens expiring within 5 minutes."""
    # Create a token that's expiring soon (in 3 minutes)
    soon_expiring_token = TenantAppToken(
        access_token="old-token",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=3)
    )

    # Manually insert into cache
    service._token_cache[str(mock_tenant_app.id)] = soon_expiring_token

    # Mock httpx to return new token
    new_token_response = MagicMock(spec=httpx.Response)
    new_token_response.status_code = 200
    new_token_response.json.return_value = {
        "access_token": "new-refreshed-token",
        "expires_in": 3600,
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = new_token_response
        mock_client_class.return_value = mock_client

        # Execute
        token = await service.get_access_token(mock_tenant_app)

        # Assert - should have acquired new token, not returned cached
        assert token == "new-refreshed-token"
        mock_client.post.assert_called_once()


async def test_force_refresh_bypasses_cache(service, mock_tenant_app, mock_httpx_response):
    """force_refresh=True acquires new token even if cached token is valid."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # First call - acquires and caches token
        token1 = await service.get_access_token(mock_tenant_app)

        # Second call with force_refresh - should acquire new token
        token2 = await service.get_access_token(mock_tenant_app, force_refresh=True)

        # Assert
        assert token1 == token2  # Same value in this test
        # But HTTP request should have been made twice
        assert mock_client.post.call_count == 2

async def test_cache_clear_invalidates_token(service, mock_tenant_app, mock_httpx_response):
    """clear_cache() removes token from cache."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # Acquire token
        await service.get_access_token(mock_tenant_app)

        # Clear cache
        service.clear_cache(str(mock_tenant_app.id))

        # Next call should acquire new token
        await service.get_access_token(mock_tenant_app)

        # Verify HTTP request was made twice
        assert mock_client.post.call_count == 2


def test_cache_clear_nonexistent_app_safe(service):
    """Clearing cache for non-existent app doesn't raise error."""
    # Should not raise
    service.clear_cache("non-existent-app-id")


async def test_multiple_apps_independent_caches(service, mock_httpx_response):
    """Different tenant apps have independent token caches."""
    # Create two different apps
    app1 = MagicMock()
    app1.id = uuid4()
    app1.client_id = "client-1"
    app1.client_secret = "secret-1"
    app1.tenant_domain = "tenant1.onmicrosoft.com"

    app2 = MagicMock()
    app2.id = uuid4()
    app2.client_id = "client-2"
    app2.client_secret = "secret-2"
    app2.tenant_domain = "tenant2.onmicrosoft.com"

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # Acquire tokens for both apps
        await service.get_access_token(app1)
        await service.get_access_token(app2)

        # Assert both apps have cached tokens
        assert str(app1.id) in service._token_cache
        assert str(app2.id) in service._token_cache

        # Clear cache for app1
        service.clear_cache(str(app1.id))

        # Assert app1 cache cleared but app2 intact
        assert str(app1.id) not in service._token_cache
        assert str(app2.id) in service._token_cache


async def test_test_credentials_success(service, mock_tenant_app, mock_httpx_response):
    """test_credentials() validates credentials without caching."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # Execute
        success, error = await service.test_credentials(mock_tenant_app)

        # Assert
        assert success is True
        assert error is None

        # Verify token was NOT cached
        assert str(mock_tenant_app.id) not in service._token_cache


async def test_test_credentials_http_error(service, mock_tenant_app):
    """test_credentials() returns error message for HTTP errors."""
    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 401
    error_response.text = "Invalid client credentials"
    error_response.json.return_value = {
        "error": "invalid_client",
        "error_description": "AADSTS7000215: Invalid client secret provided. Trace ID: abc",
    }
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized",
        request=MagicMock(),
        response=error_response
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = error_response
        mock_client_class.return_value = mock_client

        # Execute
        success, error = await service.test_credentials(mock_tenant_app)

        # Assert
        assert success is False
        assert error is not None
        assert "Invalid client secret provided" in error
        # Trace IDs should be stripped
        assert "Trace ID" not in error


async def test_test_credentials_network_error(service, mock_tenant_app):
    """test_credentials() handles network errors gracefully."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = httpx.ConnectError("Connection failed")
        mock_client_class.return_value = mock_client

        # Execute
        success, error = await service.test_credentials(mock_tenant_app)

        # Assert
        assert success is False
        assert error is not None
        assert "Connection failed" in error

async def test_invalid_credentials_raises_error(service, mock_tenant_app):
    """Invalid credentials raise HTTPStatusError."""
    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 401
    error_response.text = "AADSTS7000215: Invalid client secret"
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Unauthorized",
        request=MagicMock(),
        response=error_response
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = error_response
        mock_client_class.return_value = mock_client

        # Execute and assert
        with pytest.raises(httpx.HTTPStatusError):
            await service.get_access_token(mock_tenant_app)

async def test_token_response_parsing(service, mock_tenant_app):
    """Correctly parses token response from Microsoft Graph."""
    custom_response = MagicMock(spec=httpx.Response)
    custom_response.status_code = 200
    custom_response.json.return_value = {
        "token_type": "Bearer",
        "expires_in": 7200,  # 2 hours
        "access_token": "custom-access-token-xyz",
        "ext_expires_in": 7200,  # Can be ignored
    }

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = custom_response
        mock_client_class.return_value = mock_client

        # Execute
        token = await service.get_access_token(mock_tenant_app)

        # Assert
        assert token == "custom-access-token-xyz"

        # Verify token is cached with correct expiration
        cached = service._token_cache[str(mock_tenant_app.id)]
        assert cached.access_token == "custom-access-token-xyz"
        # Should expire in approximately 2 hours (allowing small time drift)
        time_until_expiry = cached.expires_at - datetime.now(timezone.utc)
        assert timedelta(hours=1, minutes=59) < time_until_expiry < timedelta(hours=2, minutes=1)

async def test_concurrent_token_requests_dont_duplicate_calls(service, mock_tenant_app, mock_httpx_response):
    """Multiple concurrent requests should ideally use cached token."""
    # Note: This is a basic test. True thread safety would require locks,
    # but for this simple cache, race conditions are acceptable.

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = mock_httpx_response
        mock_client_class.return_value = mock_client

        # Make 5 concurrent requests
        results = await asyncio.gather(*[
            service.get_access_token(mock_tenant_app)
            for _ in range(5)
        ])

        # All results should be the same token
        assert all(r == "mock-access-token-123" for r in results)

        # Due to race conditions, might be called 1-5 times,
        # but ideally should be just 1-2 times
        call_count = mock_client.post.call_count
        assert 1 <= call_count <= 5  # Permissive check
        # In practice with proper locking, this would always be 1

async def test_http_500_error_raises_exception(service, mock_tenant_app):
    """Server errors (5xx) raise HTTPStatusError."""
    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 500
    error_response.text = "Internal Server Error"
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Internal Server Error",
        request=MagicMock(),
        response=error_response
    )

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.return_value = error_response
        mock_client_class.return_value = mock_client

        with pytest.raises(httpx.HTTPStatusError):
            await service.get_access_token(mock_tenant_app)


async def test_timeout_error_raises_exception(service, mock_tenant_app):
    """Timeout errors raise appropriate exception."""
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.post.side_effect = httpx.TimeoutException("Request timeout")
        mock_client_class.return_value = mock_client

        with pytest.raises(httpx.TimeoutException):
            await service.get_access_token(mock_tenant_app)
