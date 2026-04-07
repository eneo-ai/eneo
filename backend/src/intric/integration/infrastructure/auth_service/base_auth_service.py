from abc import ABC, abstractmethod
from typing import Any, Optional, TypedDict
from uuid import UUID

DEFAULT_AUTH_TIMEOUT = 20


class TokenResponse(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: str
    token_type: str
    scope: str


class BaseOauthService(ABC):
    @abstractmethod
    async def gen_auth_url(
        self, state: Optional[str] = None, tenant_id: Optional[UUID] = None
    ) -> dict[str, str]: ...
    @abstractmethod
    async def get_resources(
        self, access_token: str, tenant_id: Optional[UUID] = None
    ) -> list[dict[str, Any]]: ...
    @abstractmethod
    async def exchange_token(
        self, auth_code: str, tenant_id: Optional[UUID] = None
    ) -> TokenResponse | None: ...
    @abstractmethod
    async def refresh_access_token(
        self, refresh_token: str, tenant_id: Optional[UUID] = None
    ) -> TokenResponse | None: ...
