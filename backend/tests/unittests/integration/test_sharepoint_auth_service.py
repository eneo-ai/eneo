"""Unit tests for SharepointAuthService - OAuth2 authentication for SharePoint.

Tests the OAuth URL generation, token exchange, and token refresh functionality
for personal SharePoint integrations.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from intric.integration.infrastructure.auth_service.sharepoint_auth_service import (
    SharepointAuthService,
)


@pytest.fixture
def mock_tenant_app():
    """Create a mock tenant SharePoint app."""
    app = MagicMock()
    app.id = uuid4()
    app.client_id = "test-client-id-123"
    app.client_secret = "test-client-secret-456"
    app.tenant_domain = "contoso.onmicrosoft.com"
    app.is_active = True
    return app


@pytest.fixture
def mock_tenant_app_service(mock_tenant_app):
    """Create a mock tenant SharePoint app service."""
    service = AsyncMock()
    service.get_active_app_for_tenant = AsyncMock(return_value=mock_tenant_app)
    return service


@pytest.fixture
def service(mock_tenant_app_service):
    """Create SharepointAuthService with mocked dependencies."""
    return SharepointAuthService(tenant_sharepoint_app_service=mock_tenant_app_service)


@pytest.fixture
def mock_token_response():
    """Create a mock successful token response."""
    return {
        "token_type": "Bearer",
        "expires_in": 3600,
        "access_token": "mock-access-token-xyz",
        "refresh_token": "mock-refresh-token-abc",
        "scope": "Files.Read.All Sites.Read.All User.Read Group.Read.All",
    }


class TestGetCredentials:
    """Tests for get_credentials method."""

    async def test_gets_credentials_from_tenant_app(
        self, service, mock_tenant_app_service, mock_tenant_app
    ):
        """Successfully retrieves credentials from tenant app configuration."""
        tenant_id = uuid4()

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            creds = await service.get_credentials(tenant_id)

        assert creds["client_id"] == mock_tenant_app.client_id
        assert creds["client_secret"] == mock_tenant_app.client_secret
        assert creds["tenant_domain"] == mock_tenant_app.tenant_domain
        assert creds["redirect_uri"] == "https://example.com/callback"
        assert "login.microsoftonline.com" in creds["authority"]
        assert mock_tenant_app.tenant_domain in creds["authority"]

    async def test_raises_error_if_no_tenant_app_configured(
        self, mock_tenant_app_service
    ):
        """Raises ValueError if no SharePoint app is configured."""
        mock_tenant_app_service.get_active_app_for_tenant = AsyncMock(return_value=None)
        svc = SharepointAuthService(tenant_sharepoint_app_service=mock_tenant_app_service)

        with pytest.raises(ValueError, match="SharePoint OAuth not configured"):
            await svc.get_credentials(uuid4())

    async def test_uses_default_redirect_uri_if_not_configured(
        self, service, mock_tenant_app_service
    ):
        """Uses public_origin + default path if oauth_callback_url not set."""
        tenant_id = uuid4()

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = None
            settings.public_origin = "https://myapp.example.com"
            mock_settings.return_value = settings

            creds = await service.get_credentials(tenant_id)

        assert creds["redirect_uri"] == "https://myapp.example.com/integrations/callback/token/"

    async def test_raises_error_if_no_redirect_uri_configured(
        self, service, mock_tenant_app_service
    ):
        """Raises ValueError if neither oauth_callback_url nor public_origin is set."""
        tenant_id = uuid4()

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = None
            settings.public_origin = None
            mock_settings.return_value = settings

            with pytest.raises(ValueError, match="OAUTH_CALLBACK_URL or PUBLIC_ORIGIN"):
                await service.get_credentials(tenant_id)


class TestGenAuthUrl:
    """Tests for gen_auth_url method."""

    async def test_returns_valid_microsoft_url(self, service):
        """Returns a valid Microsoft OAuth authorization URL."""
        tenant_id = uuid4()
        state = "random-state-token"

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            result = await service.gen_auth_url(state=state, tenant_id=tenant_id)

        assert "auth_url" in result
        assert "login.microsoftonline.com" in result["auth_url"]
        assert "oauth2/v2.0/authorize" in result["auth_url"]

    async def test_includes_required_scopes(self, service):
        """Auth URL includes required SharePoint scopes."""
        tenant_id = uuid4()

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            result = await service.gen_auth_url(state="state", tenant_id=tenant_id)

        auth_url = result["auth_url"]
        assert "offline_access" in auth_url
        assert "Files.Read.All" in auth_url
        assert "Sites.Read.All" in auth_url
        assert "User.Read" in auth_url
        assert "Group.Read.All" in auth_url

    async def test_includes_state_parameter(self, service):
        """Auth URL includes the state parameter for CSRF protection."""
        tenant_id = uuid4()
        state = "my-unique-state-123"

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            result = await service.gen_auth_url(state=state, tenant_id=tenant_id)

        assert f"state={state}" in result["auth_url"]

    async def test_includes_prompt_login(self, service):
        """Auth URL includes prompt=login to force login without consent screen."""
        tenant_id = uuid4()

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            result = await service.gen_auth_url(state="state", tenant_id=tenant_id)

        assert "prompt=login" in result["auth_url"]


class TestExchangeToken:
    """Tests for exchange_token method."""

    async def test_exchange_token_success(self, service, mock_token_response):
        """Successfully exchanges auth code for tokens."""
        tenant_id = uuid4()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                result = await service.exchange_token(
                    auth_code="auth-code-123",
                    tenant_id=tenant_id,
                )

        assert result["access_token"] == "mock-access-token-xyz"
        assert result["refresh_token"] == "mock-refresh-token-abc"

    async def test_exchange_token_sends_correct_data(self, service, mock_token_response):
        """Sends correct payload to Microsoft token endpoint."""
        tenant_id = uuid4()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                await service.exchange_token(
                    auth_code="test-auth-code",
                    tenant_id=tenant_id,
                )

        # Verify POST was called with correct data
        call_args = mock_client.post.call_args
        posted_data = call_args.kwargs["data"]
        assert posted_data["grant_type"] == "authorization_code"
        assert posted_data["code"] == "test-auth-code"
        assert "client_id" in posted_data
        assert "client_secret" in posted_data

    async def test_exchange_token_invalid_code_raises_error(self, service):
        """Raises HTTPStatusError for invalid auth code."""
        tenant_id = uuid4()

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 400
        error_response.text = "invalid_grant"
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=error_response
        )

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = error_response
                mock_client_class.return_value = mock_client

                with pytest.raises(httpx.HTTPStatusError):
                    await service.exchange_token(
                        auth_code="invalid-code",
                        tenant_id=tenant_id,
                    )


class TestRefreshAccessToken:
    """Tests for refresh_access_token method."""

    async def test_refresh_access_token_success(self, service, mock_token_response):
        """Successfully refreshes access token."""
        tenant_id = uuid4()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                result = await service.refresh_access_token(
                    refresh_token="old-refresh-token",
                    tenant_id=tenant_id,
                )

        assert result["access_token"] == "mock-access-token-xyz"
        assert result["refresh_token"] == "mock-refresh-token-abc"

    async def test_refresh_sends_correct_grant_type(self, service, mock_token_response):
        """Sends grant_type=refresh_token in request."""
        tenant_id = uuid4()

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = mock_response
                mock_client_class.return_value = mock_client

                await service.refresh_access_token(
                    refresh_token="my-refresh-token",
                    tenant_id=tenant_id,
                )

        posted_data = mock_client.post.call_args.kwargs["data"]
        assert posted_data["grant_type"] == "refresh_token"
        assert posted_data["refresh_token"] == "my-refresh-token"

    async def test_refresh_expired_token_raises_error(self, service):
        """Raises HTTPStatusError for expired refresh token."""
        tenant_id = uuid4()

        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 400
        error_response.text = "invalid_grant: The refresh token has expired"
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=error_response
        )

        with patch("intric.integration.infrastructure.auth_service.sharepoint_auth_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.oauth_callback_url = "https://example.com/callback"
            settings.public_origin = "https://example.com"
            mock_settings.return_value = settings

            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.__aexit__.return_value = None
                mock_client.post.return_value = error_response
                mock_client_class.return_value = mock_client

                with pytest.raises(httpx.HTTPStatusError):
                    await service.refresh_access_token(
                        refresh_token="expired-refresh-token",
                        tenant_id=tenant_id,
                    )


class TestGetResources:
    """Tests for get_resources method."""

    async def test_get_resources_success(self, service):
        """Successfully retrieves SharePoint root site info."""
        mock_site_data = {
            "id": "root-site-id",
            "displayName": "Root Site",
            "webUrl": "https://contoso.sharepoint.com",
        }

        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_site_data

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = await service.get_resources(access_token="valid-token")

        assert result["id"] == "root-site-id"
        assert result["displayName"] == "Root Site"

    async def test_get_resources_sends_authorization_header(self, service):
        """Sends Bearer token in Authorization header."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "site-id"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = mock_response
            mock_client_class.return_value = mock_client

            await service.get_resources(access_token="my-access-token")

        call_headers = mock_client.get.call_args.kwargs["headers"]
        assert call_headers["Authorization"] == "Bearer my-access-token"

    async def test_get_resources_invalid_token_raises_error(self, service):
        """Raises HTTPStatusError for invalid access token."""
        error_response = MagicMock(spec=httpx.Response)
        error_response.status_code = 401
        error_response.text = "Unauthorized"
        error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=error_response
        )

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.get.return_value = error_response
            mock_client_class.return_value = mock_client

            with pytest.raises(httpx.HTTPStatusError):
                await service.get_resources(access_token="invalid-token")
