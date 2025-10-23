from logging import getLogger

import httpx

from intric.integration.infrastructure.auth_service.base_auth_service import (
    DEFAULT_AUTH_TIMEOUT,
    BaseOauthService,
    TokenResponse,
)
from intric.main.config import get_settings

logger = getLogger(__name__)


class SharepointAuthService(BaseOauthService):
    SCOPES = ["Sites.Read.All"]

    def __init__(self):
        self.authority = "https://login.microsoftonline.com/common"

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
        scope = "%20".join(self.SCOPES)
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": f"offline_access {scope}",
            "state": state,
            "prompt": "consent",
        }

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        url = f"{auth_endpoint}?{query_string}"
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
