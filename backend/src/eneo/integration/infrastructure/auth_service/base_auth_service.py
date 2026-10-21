from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

import httpx
from typing_extensions import TypedDict

from eneo.integration.infrastructure.auth_service.org_token_provider import (
    aadsts_code,
    token_endpoint_error,
)
from eneo.integration.infrastructure.content_service.types import OAuthResource

DEFAULT_AUTH_TIMEOUT = 20


def _reference(exc: httpx.HTTPStatusError) -> str:
    code = aadsts_code(exc)
    return f" ({code})" if code else ""


class OAuthCodeRejectedError(Exception):
    """The identity provider refused the authorization code (``invalid_grant``):
    expired, already used, or issued for another redirect URI.

    Served as a 400 with ``code`` below. The state that carried the code is
    spent, so the person has to start the sign-in again.
    """

    code = "oauth_code_rejected"

    def __init__(self, exc: httpx.HTTPStatusError) -> None:
        super().__init__(
            "The sign-in could not be completed: the sign-in provider did not "
            f"accept the authorization code{_reference(exc)}. Start the sign-in "
            "again."
        )


class OAuthClientRejectedError(Exception):
    """The identity provider refused the app's own credentials
    (``invalid_client``, ``unauthorized_client``): a wrong or expired client
    secret, or an app not allowed this sign-in. Signing in again cannot help.

    Served as a 400 with ``code`` below.
    """

    code = "oauth_client_rejected"

    def __init__(self, exc: httpx.HTTPStatusError) -> None:
        super().__init__(
            "The sign-in could not be completed: the sign-in provider did not "
            f"accept the app's credentials{_reference(exc)}. An administrator "
            "must check the app's client ID and client secret."
        )


_CLIENT_ERRORS = frozenset({"invalid_client", "unauthorized_client"})


def token_exchange_rejection(
    exc: httpx.HTTPStatusError,
) -> OAuthCodeRejectedError | OAuthClientRejectedError | None:
    """What a refused code exchange means for the caller; None keeps it a
    server error (throttling, outages, malformed requests)."""
    status = exc.response.status_code
    error = token_endpoint_error(exc)
    if status == 400 and error == "invalid_grant":
        return OAuthCodeRejectedError(exc)
    if status == 401 or (400 <= status < 500 and error in _CLIENT_ERRORS):
        return OAuthClientRejectedError(exc)
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
