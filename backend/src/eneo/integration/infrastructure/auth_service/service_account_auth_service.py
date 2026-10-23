"""Service Account authentication service for SharePoint.

Handles OAuth flow for service account authentication, which uses delegated
permissions (like user OAuth) but with a dedicated service account.
This provides granular access control without person-dependency.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging import getLogger
from typing import TYPE_CHECKING, Optional, cast
from urllib.parse import urlencode

import httpx

from eneo.integration.infrastructure.auth_service.base_auth_service import (
    DEFAULT_AUTH_TIMEOUT,
    TokenResponse,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    loggable_token_reason,
)
from eneo.integration.infrastructure.auth_service.tenant_app_auth_service import (
    TenantAppToken,
)
from eneo.main.config import get_settings

if TYPE_CHECKING:
    from eneo.integration.domain.entities.tenant_sharepoint_app import (
        TenantSharePointApp,
    )

logger = getLogger(__name__)

_DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS = 3600


def _credentials_fingerprint(app: "TenantSharePointApp") -> str:
    """Identifies the app credentials and the signed-in account, never the secret."""
    material = "\x00".join(
        (
            app.tenant_domain,
            app.client_id,
            app.client_secret,
            app.service_account_email or "",
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


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

    # User.Read identifies the service account and exposes its direct group IDs
    # for membership-based site categorization.
    DEFAULT_SCOPES = ["Files.Read.All", "Sites.Read.All", "User.Read"]

    def __init__(self) -> None:
        super().__init__()
        self.default_scopes = self.DEFAULT_SCOPES
        self._token_cache: dict[str, TenantAppToken] = {}

    def _build_credentials(
        self,
        client_id: str,
        client_secret: str,
        tenant_domain: str,
        include_redirect_uri: bool = True,
        redirect_uri: str | None = None,
    ) -> ServiceAccountCredentials:
        """Build credentials object from provided values.

        Args:
            client_id: Microsoft Entra ID application client ID
            client_secret: Microsoft Entra ID application client secret
            tenant_domain: Microsoft Entra ID tenant domain
            include_redirect_uri: Whether to include redirect_uri (only needed for OAuth flow)
        """
        redirect_uri = (
            get_settings().integration_callback_uri(redirect_uri)
            if include_redirect_uri
            else None
        )
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
        redirect_uri: str | None = None,
    ) -> dict[str, str]:
        """Generate OAuth authorization URL for service account login.

        Args:
            state: OAuth state parameter for CSRF protection
            client_id: Microsoft Entra ID application client ID
            client_secret: Microsoft Entra ID application client secret
            tenant_domain: Microsoft Entra ID tenant domain (e.g., contoso.onmicrosoft.com)

        Returns:
            Dictionary with 'auth_url' key containing the authorization URL
        """
        creds = self._build_credentials(
            client_id, client_secret, tenant_domain, redirect_uri=redirect_uri
        )
        auth_endpoint = f"{creds.authority}/oauth2/v2.0/authorize"
        scope_param = " ".join(["offline_access", *self.default_scopes])

        params = {
            "client_id": creds.client_id,
            "response_type": "code",
            "redirect_uri": creds.redirect_uri,
            "response_mode": "query",
            "scope": scope_param,
            "state": state,
            "prompt": "login",
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
        redirect_uri: str | None = None,
    ) -> ServiceAccountTokenResult:
        """Exchange authorization code for access and refresh tokens.

        Args:
            auth_code: OAuth authorization code from callback
            client_id: Microsoft Entra ID application client ID
            client_secret: Microsoft Entra ID application client secret
            tenant_domain: Microsoft Entra ID tenant domain

        Returns:
            ServiceAccountTokenResult with access_token, refresh_token, and email
        """
        creds = self._build_credentials(
            client_id, client_secret, tenant_domain, redirect_uri=redirect_uri
        )
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
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Service account token exchange failed: %s",
                        loggable_token_reason(exc),
                    )
                    raise

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
        *,
        force_refresh: bool = False,
    ) -> TokenResponse:
        """An access token for the service account, refreshed when needed.

        Microsoft rotates the refresh token on every refresh, so refreshing on
        each acquisition would rotate it for every page browsed, sync run and
        subscription renewed. A token minted earlier in this process is reused
        until it is about to expire; such a response carries no refresh_token,
        so callers persist a rotation only when one happened. The cache is per
        process and keyed by a credential fingerprint, so a reconfigured secret
        or another signed-in account is never a hit.

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

        cache_key = str(tenant_app.id)
        fingerprint = _credentials_fingerprint(tenant_app)
        cached = self._token_cache.get(cache_key)
        if (
            not force_refresh
            and cached is not None
            and cached.credentials_fingerprint == fingerprint
            and not cached.is_expiring_soon()
        ):
            return cast(TokenResponse, {"access_token": cached.access_token})

        token_data = await self._refresh(tenant_app)
        try:
            lifetime = int(token_data.get("expires_in") or 0)
        except (TypeError, ValueError):
            lifetime = 0
        self._token_cache[cache_key] = TenantAppToken(
            access_token=token_data["access_token"],
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=lifetime or _DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS),
            credentials_fingerprint=fingerprint,
        )
        return token_data

    async def _refresh(self, tenant_app: "TenantSharePointApp") -> TokenResponse:
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
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "Service account token refresh failed for tenant %s: %s",
                        tenant_app.tenant_id,
                        loggable_token_reason(exc),
                    )
                    raise

            token_data = response.json()
            logger.debug(
                f"Service account token refreshed for tenant {tenant_app.tenant_id}"
            )

            return token_data
