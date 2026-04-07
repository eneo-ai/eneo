import uuid
from typing import Optional
from urllib.parse import urlencode

import httpx
from typing_extensions import override

from intric.integration.infrastructure.auth_service.base_auth_service import (
    DEFAULT_AUTH_TIMEOUT,
    BaseOauthService,
    TokenResponse,
)
from intric.integration.infrastructure.content_service.types import OAuthResource
from intric.main.config import get_settings


class ConfluenceAuthService(BaseOauthService):
    def __init__(self) -> None:
        super().__init__()
        self.SCOPE_SEPARATOR = " "
        self._scopes = [
            "read:me",
            "read:confluence-content.all",
            "offline_access",
            "search:confluence",
            "read:confluence-content.permission",
            "read:confluence-user",
            "read:confluence-groups",
            "read:confluence-space.summary",
            "read:confluence-props",
            "read:confluence-content.summary",
            "readonly:content.attachment:confluence",
        ]

    @property
    def _client_id(self) -> str:
        client_id = get_settings().confluence_client_id
        if client_id is None:
            raise ValueError("CONFLUENCE_CLIENT_ID is not set")
        return client_id

    @property
    def _client_secret(self) -> str:
        client_secret = get_settings().confluence_client_secret
        if client_secret is None:
            raise ValueError("CONFLUENCE_CLIENT_SECRET is not set")
        return client_secret

    @property
    def _redirect_uri(self) -> str:
        redirect_uri = get_settings().oauth_callback_url
        if redirect_uri is None:
            raise ValueError("OAUTH_CALLBACK_URL is not set")
        return redirect_uri

    @override
    async def gen_auth_url(
        self, state: Optional[str] = None, tenant_id: Optional[uuid.UUID] = None
    ) -> dict[str, str]:
        params = {
            "audience": "api.atlassian.com",
            "client_id": self._client_id,
            "scope": self.SCOPE_SEPARATOR.join(self._scopes),
            "redirect_uri": self._redirect_uri,
            "state": state or str(uuid.uuid4()),
            "response_type": "code",
            "prompt": "consent",
        }
        auth_base_url = "https://auth.atlassian.com/authorize"
        url = f"{auth_base_url}?{urlencode(params)}"
        return {"auth_url": url}

    @override
    async def get_resources(
        self, access_token: str, tenant_id: Optional[uuid.UUID] = None
    ) -> list[OAuthResource]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.atlassian.com/oauth/token/accessible-resources",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=DEFAULT_AUTH_TIMEOUT,
            )
            if response.status_code == 200:
                result: list[OAuthResource] = response.json()
                return result
            else:
                response.raise_for_status()
                raise RuntimeError("Failed to fetch Confluence resources")

    @override
    async def exchange_token(
        self, auth_code: str, tenant_id: Optional[uuid.UUID] = None
    ) -> TokenResponse | None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://auth.atlassian.com/oauth/token",
                headers={"Content-Type": "application/json"},
                json=(
                    {
                        "grant_type": "authorization_code",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "code": auth_code,
                        "redirect_uri": self._redirect_uri,
                    }
                ),
                timeout=DEFAULT_AUTH_TIMEOUT,
            )

            if response.status_code == 200:
                return response.json()
            else:
                response.raise_for_status()

    @override
    async def refresh_access_token(
        self, refresh_token: str, tenant_id: Optional[uuid.UUID] = None
    ) -> TokenResponse | None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://auth.atlassian.com/oauth/token",
                headers={"Content-Type": "application/json"},
                json=(
                    {
                        "grant_type": "refresh_token",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "refresh_token": refresh_token,
                    }
                ),
                timeout=DEFAULT_AUTH_TIMEOUT,
            )

            if response.status_code == 200:
                return response.json()
            else:
                response.raise_for_status()
