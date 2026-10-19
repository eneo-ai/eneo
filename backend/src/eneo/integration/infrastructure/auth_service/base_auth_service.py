from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

import httpx
from typing_extensions import TypedDict

from eneo.integration.infrastructure.auth_service.org_token_provider import (
    summarize_token_endpoint_error,
)
from eneo.integration.infrastructure.content_service.types import OAuthResource
from eneo.observability.error_text import user_visible_error

DEFAULT_AUTH_TIMEOUT = 20


class OAuthCodeRejectedError(Exception):
    """The identity provider refused an authorization code at the callback:
    expired, already used, or issued for another app or redirect URI.

    Served as a 400 with ``code`` below. The state that carried the code is
    spent, so the person has to start the sign-in again.
    """

    code = "oauth_code_rejected"

    def __init__(self, reason: str) -> None:
        super().__init__(
            "The sign-in could not be completed "
            f"({user_visible_error(reason)}). Start the sign-in again."
        )


def rejected_code(exc: httpx.HTTPStatusError) -> OAuthCodeRejectedError | None:
    """The rejection a token-endpoint 4xx stands for; None for a server error."""
    if 400 <= exc.response.status_code < 500:
        return OAuthCodeRejectedError(summarize_token_endpoint_error(exc))
    return None


class TokenResponse(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: str
    token_type: str
    scope: str


class BaseOauthService(ABC):
    @abstractmethod
    async def gen_auth_url(
        self,
        state: Optional[str] = None,
        tenant_id: Optional[UUID] = None,
        *,
        redirect_uri: str | None = None,
    ) -> dict[str, str]: ...
    @abstractmethod
    async def get_resources(
        self, access_token: str, tenant_id: Optional[UUID] = None
    ) -> list[OAuthResource]: ...
    @abstractmethod
    async def exchange_token(
        self,
        auth_code: str,
        tenant_id: Optional[UUID] = None,
        *,
        redirect_uri: str | None = None,
    ) -> TokenResponse | None: ...
    @abstractmethod
    async def refresh_access_token(
        self, refresh_token: str, tenant_id: Optional[UUID] = None
    ) -> TokenResponse | None: ...
