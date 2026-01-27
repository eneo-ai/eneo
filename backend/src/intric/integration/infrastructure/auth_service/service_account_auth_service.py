"""Service Account authentication service for SharePoint.

Handles OAuth flow for service account authentication, which uses delegated
permissions (like user OAuth) but with a dedicated service account.
This provides granular access control without person-dependency.
"""

from dataclasses import dataclass
from logging import getLogger
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlencode

import httpx

from intric.integration.infrastructure.auth_service.base_auth_service import (
    DEFAULT_AUTH_TIMEOUT,
    TokenResponse,
)
from intric.main.config import get_settings

if TYPE_CHECKING:
    from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp

logger = getLogger(__name__)


@dataclass
class ServiceAccountCredentials:
    """Credentials for service account OAuth flow."""
    client_id: str
    client_secret: str
    tenant_domain: str
    authority: str
    redirect_uri: Optional[str] = None  # Only needed for OAuth flow, not for refresh


@dataclass
class ServiceAccountTokenResult:
    """Result of service account token exchange."""
    access_token: str
    refresh_token: str
    email: Optional[str] = None


class ServiceAccountAuthService:
    """Handles OAuth flow and token refresh for service account authentication.

    Service accounts use the same OAuth flow as regular users (delegated permissions)
    but with a dedicated service account. This provides:
    - Granular access control (Sites.Selected works with delegated permissions)
    - No person-dependency (service account is shared across the organization)
    - Refresh token for long-term access without re-authentication
    """

    DEFAULT_SCOPES = ["Files.Read.All", "Sites.Read.All", "User.Read"]

    def __init__(self):
        self.default_scopes = self.DEFAULT_SCOPES

    def _get_redirect_uri(self) -> str:
        """Get the OAuth redirect URI for service account flow."""
        settings = get_settings()
        redirect_uri = settings.oauth_callback_url
        if not redirect_uri:
            if settings.public_origin:
                redirect_uri = f"{settings.public_origin}/integrations/callback/token/"
            else:
                raise ValueError(
                    "OAUTH_CALLBACK_URL or PUBLIC_ORIGIN must be set for service account authentication"
                )
        return redirect_uri

    def _build_credentials(
        self,
        client_id: str,
        client_secret: str,
        tenant_domain: str,
        include_redirect_uri: bool = True,
    ) -> ServiceAccountCredentials:
        """Build credentials object from provided values.

        Args:
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            tenant_domain: Azure AD tenant domain
            include_redirect_uri: Whether to include redirect_uri (only needed for OAuth flow)
        """
        redirect_uri = self._get_redirect_uri() if include_redirect_uri else None
        return ServiceAccountCredentials(
            client_id=client_id,
            client_secret=client_secret,
            tenant_domain=tenant_domain,
            authority=f"https://login.microsoftonline.com/{tenant_domain}",
            redirect_uri=redirect_uri,
        )

    def _build_credentials_from_app(
        self,
        tenant_app: "TenantSharePointApp",
        include_redirect_uri: bool = True,
    ) -> ServiceAccountCredentials:
        """Build credentials from TenantSharePointApp entity.

        Args:
            tenant_app: TenantSharePointApp with service account configuration
            include_redirect_uri: Whether to include redirect_uri (only needed for OAuth flow)
        """
        return self._build_credentials(
            client_id=tenant_app.client_id,
            client_secret=tenant_app.client_secret,
            tenant_domain=tenant_app.tenant_domain,
            include_redirect_uri=include_redirect_uri,
        )

    def gen_auth_url(
        self,
        state: str,
        client_id: str,
        client_secret: str,
        tenant_domain: str,
    ) -> dict:
        """Generate OAuth authorization URL for service account login.

        Args:
            state: OAuth state parameter for CSRF protection
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            tenant_domain: Azure AD tenant domain (e.g., contoso.onmicrosoft.com)

        Returns:
            Dictionary with 'auth_url' key containing the authorization URL
        """
        creds = self._build_credentials(client_id, client_secret, tenant_domain)
        auth_endpoint = f"{creds.authority}/oauth2/v2.0/authorize"
        scope_param = " ".join(["offline_access", *self.default_scopes])

        params = {
            "client_id": creds.client_id,
            "response_type": "code",
            "redirect_uri": creds.redirect_uri,
            "response_mode": "query",
            "scope": scope_param,
            "state": state,
            "prompt": "consent",
        }

        url = f"{auth_endpoint}?{urlencode(params)}"
        logger.info(f"Generated service account auth URL for tenant {tenant_domain}")
        return {"auth_url": url}

    async def exchange_token(
        self,
        auth_code: str,
        client_id: str,
        client_secret: str,
        tenant_domain: str,
    ) -> ServiceAccountTokenResult:
        """Exchange authorization code for access and refresh tokens.

        Args:
            auth_code: OAuth authorization code from callback
            client_id: Azure AD application client ID
            client_secret: Azure AD application client secret
            tenant_domain: Azure AD tenant domain

        Returns:
            ServiceAccountTokenResult with access_token, refresh_token, and email
        """
        creds = self._build_credentials(client_id, client_secret, tenant_domain)
        token_endpoint = f"{creds.authority}/oauth2/v2.0/token"

        data = {
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "code": auth_code,
            "redirect_uri": creds.redirect_uri,
            "grant_type": "authorization_code",
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_endpoint,
                headers=headers,
                data=data,
                timeout=DEFAULT_AUTH_TIMEOUT,
            )

            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                response.raise_for_status()

            token_data = response.json()

            # Get user email from Microsoft Graph
            email = await self._get_user_email(token_data["access_token"])

            logger.info(f"Service account token exchange successful for {email}")

            return ServiceAccountTokenResult(
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                email=email,
            )

    async def _get_user_email(self, access_token: str) -> Optional[str]:
        """Get the email of the authenticated service account."""
        graph_endpoint = "https://graph.microsoft.com/v1.0/me"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(
                graph_endpoint,
                headers=headers,
                timeout=DEFAULT_AUTH_TIMEOUT,
            )

            if response.status_code == 200:
                user_data = response.json()
                return user_data.get("mail") or user_data.get("userPrincipalName")
            else:
                logger.warning(f"Failed to get user email: {response.status_code}")
                return None

    async def refresh_access_token(
        self,
        tenant_app: "TenantSharePointApp",
    ) -> TokenResponse:
        """Refresh access token using stored refresh token.

        Args:
            tenant_app: TenantSharePointApp with service account configuration

        Returns:
            TokenResponse with new access_token and potentially new refresh_token

        Raises:
            ValueError: If tenant_app is not configured for service account
        """
        if not tenant_app.is_service_account():
            raise ValueError(
                f"TenantSharePointApp {tenant_app.id} is not configured for service account"
            )

        if not tenant_app.service_account_refresh_token:
            raise ValueError(
                f"TenantSharePointApp {tenant_app.id} has no service account refresh token"
            )

        # Refresh token flow doesn't require redirect_uri
        creds = self._build_credentials_from_app(tenant_app, include_redirect_uri=False)
        token_endpoint = f"{creds.authority}/oauth2/v2.0/token"

        data = {
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "refresh_token": tenant_app.service_account_refresh_token,
            "grant_type": "refresh_token",
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_endpoint,
                headers=headers,
                data=data,
                timeout=DEFAULT_AUTH_TIMEOUT,
            )

            if response.status_code != 200:
                logger.error(
                    f"Service account token refresh failed for tenant {tenant_app.tenant_id}: "
                    f"{response.text}"
                )
                response.raise_for_status()

            token_data = response.json()
            logger.debug(
                f"Service account token refreshed for tenant {tenant_app.tenant_id}"
            )

            return token_data

    async def test_refresh_token(
        self,
        tenant_app: "TenantSharePointApp",
    ) -> tuple[bool, Optional[str]]:
        """Test if the service account refresh token is valid.

        Args:
            tenant_app: TenantSharePointApp with service account configuration

        Returns:
            Tuple of (success, error_message)
        """
        try:
            await self.refresh_access_token(tenant_app)
            return True, None
        except httpx.HTTPStatusError as e:
            return False, f"HTTP {e.response.status_code}: {e.response.text}"
        except ValueError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
