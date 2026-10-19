"""Unit tests for ServiceAccountAuthService - OAuth2 for service accounts.

Tests the OAuth URL generation, token exchange, and token refresh functionality
for service account (delegated permissions) SharePoint integrations.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from eneo.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountAuthService,
    ServiceAccountCredentials,
    ServiceAccountTokenResult,
)


@pytest.fixture
def mock_tenant_app():
    """Create a mock tenant SharePoint app configured for service account."""
    app = MagicMock()
    app.id = uuid4()
    app.tenant_id = uuid4()
    app.client_id = "service-account-client-id"
    app.client_secret = "service-account-client-secret"
    app.tenant_domain = "contoso.onmicrosoft.com"
    app.service_account_refresh_token = "stored-refresh-token-123"
    app.service_account_email = "serviceaccount@contoso.com"
    app.is_service_account.return_value = True
    app.is_active = True
    return app


@pytest.fixture
def mock_tenant_app_not_service_account():
    """Create a mock tenant app NOT configured for service account."""
    app = MagicMock()
    app.id = uuid4()
    app.is_service_account.return_value = False
    app.service_account_refresh_token = None
    return app


@pytest.fixture
def mock_settings(test_settings):
    """Mock settings with oauth_callback_url configured."""
    settings = test_settings.model_copy()
    settings.oauth_callback_url = (
        "https://test.example.com/integrations/callback/token/"
    )
    settings.public_origin = "https://test.example.com"
    return settings


@pytest.fixture
def service(mock_settings):
    """Create ServiceAccountAuthService instance with mocked settings."""
    with patch(
        "eneo.integration.infrastructure.auth_service.service_account_auth_service.get_settings",
        return_value=mock_settings,
    ):
        yield ServiceAccountAuthService()


@pytest.fixture
def mock_token_response():
    """Create a mock successful token response."""
    return {
        "token_type": "Bearer",
        "expires_in": 3600,
        "access_token": "new-access-token-xyz",
        "refresh_token": "new-refresh-token-abc",
        "scope": "Files.Read.All Sites.Read.All User.Read",
    }


class TestGenAuthUrl:
    """Tests for gen_auth_url method."""

    def test_gen_auth_url_returns_valid_url(self, service):
        """Returns a valid Microsoft OAuth authorization URL."""
        result = service.gen_auth_url(
            state="random-state",
            client_id="client-123",
            client_secret="secret-456",
            tenant_domain="contoso.onmicrosoft.com",
        )

        assert "auth_url" in result
        assert "login.microsoftonline.com" in result["auth_url"]
        assert "contoso.onmicrosoft.com" in result["auth_url"]
        assert "oauth2/v2.0/authorize" in result["auth_url"]

    def test_gen_auth_url_includes_state(self, service):
        """Auth URL includes the state parameter."""
        result = service.gen_auth_url(
            state="my-csrf-state",
            client_id="client-123",
            client_secret="secret-456",
            tenant_domain="contoso.onmicrosoft.com",
        )

        assert "state=my-csrf-state" in result["auth_url"]

    def test_gen_auth_url_includes_required_scopes(self, service):
        """Auth URL includes required scopes."""
        result = service.gen_auth_url(
            state="state",
            client_id="client-123",
            client_secret="secret-456",
            tenant_domain="contoso.onmicrosoft.com",
        )

        auth_url = result["auth_url"]
        assert "offline_access" in auth_url
        assert "Files.Read.All" in auth_url
        assert "Sites.Read.All" in auth_url
        assert "User.Read" in auth_url

    def test_gen_auth_url_uses_correct_redirect_uri(self, mock_settings):
        """Uses correct redirect URI from settings."""
        mock_settings.oauth_callback_url = "https://myapp.com/callback"

        with patch(
            "eneo.integration.infrastructure.auth_service.service_account_auth_service.get_settings",
            return_value=mock_settings,
        ):
            service = ServiceAccountAuthService()
            result = service.gen_auth_url(
                state="state",
                client_id="client-123",
                client_secret="secret-456",
                tenant_domain="contoso.onmicrosoft.com",
            )

        assert "redirect_uri=https%3A%2F%2Fmyapp.com%2Fcallback" in result["auth_url"]

    def test_gen_auth_url_includes_prompt_login(self, service):
        """Auth URL includes prompt=login (not consent, to avoid requiring admin)."""
        result = service.gen_auth_url(
            state="state",
            client_id="client-123",
            client_secret="secret-456",
            tenant_domain="contoso.onmicrosoft.com",
        )

        assert "prompt=login" in result["auth_url"]


class TestExchangeToken:
    """Tests for exchange_token method."""

    async def test_exchange_token_success(self, service, mock_token_response):
        """Successfully exchanges auth code for tokens."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response
            mock_client.get.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"mail": "service@contoso.com"}),
            )
            mock_client_class.return_value = mock_client

            result = await service.exchange_token(
                auth_code="auth-code-123",
                client_id="client-id",
                client_secret="client-secret",
                tenant_domain="contoso.onmicrosoft.com",
            )

        assert isinstance(result, ServiceAccountTokenResult)
        assert result.access_token == "new-access-token-xyz"
        assert result.refresh_token == "new-refresh-token-abc"

    async def test_exchange_token_extracts_user_email(
        self, service, mock_token_response
    ):
        """Extracts user email from Microsoft Graph."""
        mock_token_resp = MagicMock(spec=httpx.Response)
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = mock_token_response

        mock_user_resp = MagicMock(spec=httpx.Response)
        mock_user_resp.status_code = 200
        mock_user_resp.json.return_value = {"mail": "serviceaccount@contoso.com"}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_token_resp
            mock_client.get.return_value = mock_user_resp
            mock_client_class.return_value = mock_client

            result = await service.exchange_token(
                auth_code="auth-code",
                client_id="client-id",
                client_secret="client-secret",
                tenant_domain="contoso.onmicrosoft.com",
            )

        assert result.email == "serviceaccount@contoso.com"

    async def test_exchange_token_uses_upn_if_mail_missing(
        self, service, mock_token_response
    ):
        """Falls back to userPrincipalName if mail is not set."""
        mock_token_resp = MagicMock(spec=httpx.Response)
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = mock_token_response

        mock_user_resp = MagicMock(spec=httpx.Response)
        mock_user_resp.status_code = 200
        mock_user_resp.json.return_value = {
            "mail": None,
            "userPrincipalName": "user@contoso.onmicrosoft.com",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_token_resp
            mock_client.get.return_value = mock_user_resp
            mock_client_class.return_value = mock_client

            result = await service.exchange_token(
                auth_code="auth-code",
                client_id="client-id",
                client_secret="client-secret",
                tenant_domain="contoso.onmicrosoft.com",
            )

        assert result.email == "user@contoso.onmicrosoft.com"


class TestRefreshAccessToken:
    """Tests for refresh_access_token method."""

    async def test_refresh_access_token_success(
        self, service, mock_tenant_app, mock_token_response
    ):
        """Successfully refreshes access token."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            result = await service.refresh_access_token(mock_tenant_app)

        assert result["access_token"] == "new-access-token-xyz"
        assert result["refresh_token"] == "new-refresh-token-abc"

    async def test_refresh_fails_if_not_service_account(
        self, service, mock_tenant_app_not_service_account
    ):
        """Raises ValueError if tenant app is not configured for service account."""
        with pytest.raises(ValueError, match="not configured for service account"):
            await service.refresh_access_token(mock_tenant_app_not_service_account)

    async def test_refresh_fails_without_refresh_token(self, service):
        """Raises ValueError if no refresh token stored."""
        app = MagicMock()
        app.id = uuid4()
        app.is_service_account.return_value = True
        app.service_account_refresh_token = None

        with pytest.raises(ValueError, match="no service account refresh token"):
            await service.refresh_access_token(app)

    async def test_refresh_sends_stored_refresh_token(
        self, service, mock_tenant_app, mock_token_response
    ):
        """Uses the stored refresh token from tenant app."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = mock_token_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_client.post.return_value = mock_response
            mock_client_class.return_value = mock_client

            await service.refresh_access_token(mock_tenant_app)

        posted_data = mock_client.post.call_args.kwargs["data"]
        assert (
            posted_data["refresh_token"]
            == mock_tenant_app.service_account_refresh_token
        )
        assert posted_data["grant_type"] == "refresh_token"


async def test_refresh_refusals_are_logged_without_the_body(service, mock_tenant_app):
    error_response = MagicMock(spec=httpx.Response)
    error_response.status_code = 400
    error_response.text = (
        '{"error_description": "... Trace ID: abc Correlation ID: def"}'
    )
    error_response.json.return_value = {
        "error": "invalid_client",
        "error_description": "AADSTS7000215: Invalid client secret provided. Trace ID: abc\r\nCorrelation ID: def",
    }
    error_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request", request=MagicMock(), response=error_response
    )

    with (
        patch("httpx.AsyncClient", return_value=_posting_client([error_response])),
        patch(
            "eneo.integration.infrastructure.auth_service.service_account_auth_service.logger"
        ) as log,
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await service.refresh_access_token(mock_tenant_app)

    logged = [str(call.args[0]) % call.args[1:] for call in log.error.call_args_list]
    assert logged == [
        f"Service account token refresh failed for tenant {mock_tenant_app.tenant_id}: "
        "invalid_client AADSTS7000215"
    ]


def _posting_client(responses: list[MagicMock]) -> AsyncMock:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post.side_effect = responses
    return client


def _token_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.json.return_value = payload
    return response


class TestAccessTokenCache:
    """One refresh per token lifetime, not one per acquisition."""

    async def test_a_cached_token_is_reused_without_a_rotation(
        self, service, mock_tenant_app, mock_token_response
    ):
        client = _posting_client([_token_response(mock_token_response)])

        with patch("httpx.AsyncClient", return_value=client):
            first = await service.refresh_access_token(mock_tenant_app)
            second = await service.refresh_access_token(mock_tenant_app)

        assert first["refresh_token"] == "new-refresh-token-abc"
        assert second["access_token"] == first["access_token"]
        assert second.get("refresh_token") is None
        assert client.post.call_count == 1

    @pytest.mark.parametrize(
        "miss", ["secret-changed", "account-changed", "expiring", "forced"]
    )
    async def test_the_cache_misses_when_it_must(
        self, service, mock_tenant_app, mock_token_response, miss
    ):
        if miss == "expiring":
            mock_token_response = {**mock_token_response, "expires_in": 60}
        later = {**mock_token_response, "access_token": "later-access-token"}
        client = _posting_client(
            [_token_response(mock_token_response), _token_response(later)]
        )

        with patch("httpx.AsyncClient", return_value=client):
            await service.refresh_access_token(mock_tenant_app)
            if miss == "secret-changed":
                mock_tenant_app.client_secret = "rotated-secret"
            elif miss == "account-changed":
                mock_tenant_app.service_account_email = "other@contoso.com"
            second = await service.refresh_access_token(
                mock_tenant_app, force_refresh=miss == "forced"
            )

        assert second["access_token"] == "later-access-token"
        assert client.post.call_count == 2


class TestServiceAccountCredentials:
    """Tests for ServiceAccountCredentials dataclass."""

    def test_credentials_dataclass_fields(self):
        """Credentials dataclass has all required fields."""
        creds = ServiceAccountCredentials(
            client_id="client-123",
            client_secret="secret-456",
            tenant_domain="contoso.onmicrosoft.com",
            redirect_uri="https://example.com/callback",
            authority="https://login.microsoftonline.com/contoso.onmicrosoft.com",
        )

        assert creds.client_id == "client-123"
        assert creds.client_secret == "secret-456"
        assert creds.tenant_domain == "contoso.onmicrosoft.com"
        assert creds.redirect_uri == "https://example.com/callback"
        assert (
            creds.authority
            == "https://login.microsoftonline.com/contoso.onmicrosoft.com"
        )


class TestServiceAccountTokenResult:
    """Tests for ServiceAccountTokenResult dataclass."""

    def test_token_result_dataclass_fields(self):
        """Token result dataclass has all required fields."""
        result = ServiceAccountTokenResult(
            access_token="access-123",
            refresh_token="refresh-456",
            email="service@contoso.com",
        )

        assert result.access_token == "access-123"
        assert result.refresh_token == "refresh-456"
        assert result.email == "service@contoso.com"

    def test_token_result_email_optional(self):
        """Email field is optional."""
        result = ServiceAccountTokenResult(
            access_token="access-123",
            refresh_token="refresh-456",
        )

        assert result.email is None
