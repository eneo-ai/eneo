from abc import ABC, abstractmethod
from typing import Optional, TypedDict


DEFAULT_AUTH_TIMEOUT = 20


class TokenResponse(TypedDict):
    access_token: str
    refresh_token: str
    expires_in: str
    token_type: str
    scope: str


class BaseOauthService(ABC):
    @abstractmethod
    def gen_auth_url(self, state: Optional[str] = None) -> dict: ...
    @abstractmethod
    async def get_resources(self, access_token: str) -> list[dict]: ...
    @abstractmethod
    async def exchange_token(self, auth_code: str) -> TokenResponse: ...
    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> TokenResponse: ...
