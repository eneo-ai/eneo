from logging import getLogger
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlencode
from uuid import UUID

import httpx

from intric.integration.infrastructure.auth_service.base_auth_service import (
    DEFAULT_AUTH_TIMEOUT,
    BaseOauthService,
    TokenResponse,
)
from intric.main.config import get_settings

if TYPE_CHECKING:
    from intric.integration.application.tenant_sharepoint_app_service import (
        TenantSharePointAppService,
    )

logger = getLogger(__name__)


class SharepointAuthService(BaseOauthService):
    # Personal OAuth: no User.Read needed (service account flow adds it
    # separately to retrieve the account email)
    DEFAULT_SCOPES = ["Files.Read.All", "Sites.Read.All"]

    def __init__(self, tenant_sharepoint_app_service: Optional["TenantSharePointAppService"] = None):
        self.tenant_sharepoint_app_service = tenant_sharepoint_app_service
        self.default_scopes = self.DEFAULT_SCOPES

    async def get_credentials(self, tenant_id: Optional[UUID] = None):
        """Get SharePoint OAuth credentials from admin panel configuration."""
        settings = get_settings()

        tenant_app = None
        if tenant_id and self.tenant_sharepoint_app_service:
            tenant_app = await self.tenant_sharepoint_app_service.get_active_app_for_tenant(tenant_id)

        if not tenant_app:
            raise ValueError(
                "SharePoint OAuth not configured. Please configure a SharePoint app in the admin panel."
            )

        redirect_uri = settings.oauth_callback_url
        if not redirect_uri:
            if not settings.public_origin:
                raise ValueError(
                    "SharePoint OAuth requires either OAUTH_CALLBACK_URL or PUBLIC_ORIGIN to be configured. "
                    "Set one of these environment variables to the public-facing URL of your application."
                )
            logger.warning("OAUTH_CALLBACK_URL not set, using public_origin fallback")
            redirect_uri = f"{settings.public_origin}/integrations/callback/token/"

        return {
            "client_id": tenant_app.client_id,
            "client_secret": tenant_app.client_secret,
            "tenant_domain": tenant_app.tenant_domain,
            "redirect_uri": redirect_uri,
            "authority": f"https://login.microsoftonline.com/{tenant_app.tenant_domain}",
        }

    async def gen_auth_url(self, state: str, tenant_id: Optional[UUID] = None) -> dict:
        """Generate OAuth authorization URL.

        Args:
            state: OAuth state parameter
            tenant_id: Optional tenant ID to use tenant-specific configuration
        """
        creds = await self.get_credentials(tenant_id)
        auth_endpoint = f"{creds['authority']}/oauth2/v2.0/authorize"
        scope_param = " ".join(["offline_access", *self.default_scopes])
        params = {
            "client_id": creds["client_id"],
            "response_type": "code",
            "redirect_uri": creds["redirect_uri"],
            "response_mode": "query",
            "scope": scope_param,
            "state": state,
            "prompt": "login",
        }

        url = f"{auth_endpoint}?{urlencode(params)}"
        return {"auth_url": url}

    async def exchange_token(self, auth_code: str, tenant_id: Optional[UUID] = None) -> TokenResponse:
        """Exchange authorization code for access token.

        Args:
            auth_code: OAuth authorization code
            tenant_id: Optional tenant ID to use tenant-specific configuration
        """
        creds = await self.get_credentials(tenant_id)
        token_endpoint = f"{creds['authority']}/oauth2/v2.0/token"
        data = {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "code": auth_code,
            "redirect_uri": creds["redirect_uri"],
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

            if response.status_code == 200:
                return response.json()
            else:
                response.raise_for_status()

    async def refresh_access_token(self, refresh_token: str, tenant_id: Optional[UUID] = None) -> TokenResponse:
        """Refresh access token using refresh token.

        Args:
            refresh_token: OAuth refresh token
            tenant_id: Optional tenant ID to use tenant-specific configuration
        """
        creds = await self.get_credentials(tenant_id)
        token_endpoint = f"{creds['authority']}/oauth2/v2.0/token"
        data = {
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": refresh_token,
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

            if response.status_code == 200:
                return response.json()
            else:
                response.raise_for_status()

    async def get_resources(self, access_token: str):
        graph_endpoint = "https://graph.microsoft.com/v1.0/sites/root"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(
                graph_endpoint, headers=headers, timeout=DEFAULT_AUTH_TIMEOUT
            )

            if response.status_code == 200:
                return response.json()
            else:
                response.raise_for_status()
