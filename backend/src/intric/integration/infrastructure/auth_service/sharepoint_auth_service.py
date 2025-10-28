from logging import getLogger
from urllib.parse import urlencode

import httpx

from intric.integration.infrastructure.auth_service.base_auth_service import (
    DEFAULT_AUTH_TIMEOUT,
    BaseOauthService,
    TokenResponse,
)
from intric.main.config import get_settings

logger = getLogger(__name__)


class SharepointAuthService(BaseOauthService):
    DEFAULT_SCOPES = ["Files.Read"]

    def __init__(self):
        settings = get_settings()
        tenant_id = settings.sharepoint_tenant_id
        if tenant_id:
            self.authority = f"https://login.microsoftonline.com/{tenant_id}"
        else:
            self.authority = "https://login.microsoftonline.com/common"

        configured_scopes = settings.sharepoint_scopes or ""
        scopes = [segment.strip() for segment in configured_scopes.replace(",", " ").split() if segment.strip()]
        scopes = [scope for scope in scopes if scope.lower() != "offline_access"]
        if not scopes:
            scopes = self.DEFAULT_SCOPES

        self.scopes = scopes

    @property
    def client_id(self) -> str:
        settings = get_settings()
        client_id = settings.sharepoint_client_id
        if client_id is None:
            raise ValueError("SHAREPOINT_CLIENT_ID is not set")
        return client_id

    @property
    def client_secret(self) -> str:
        settings = get_settings()
        client_secret = settings.sharepoint_client_secret
        if client_secret is None:
            raise ValueError("SHAREPOINT_CLIENT_SECRET is not set")
        return client_secret

    @property
    def redirect_uri(self) -> str:
        settings = get_settings()
        redirect_uri = settings.oauth_callback_url
        if redirect_uri is None:
            raise ValueError("OAUTH_CALLBACK_URL is not set")
        return redirect_uri

    def gen_auth_url(self, state: str) -> dict:
        auth_endpoint = f"{self.authority}/oauth2/v2.0/authorize"
        scope_param = " ".join(["offline_access", *self.scopes])
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": scope_param,
            "state": state,
            "prompt": "consent",
        }

        url = f"{auth_endpoint}?{urlencode(params)}"
        return {"auth_url": url}

    async def exchange_token(self, auth_code: str) -> TokenResponse:
        token_endpoint = f"{self.authority}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
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

    async def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        token_endpoint = f"{self.authority}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
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
