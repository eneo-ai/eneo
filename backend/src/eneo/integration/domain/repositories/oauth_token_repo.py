from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.integration.domain.entities.oauth_token import OauthToken


class OauthTokenRepository(ABC):
    @abstractmethod
    async def one_or_none(
        self, id: "UUID | None" = None, **filters: object
    ) -> "OauthToken | None": ...

    @abstractmethod
    async def one(
        self, id: "UUID | None" = None, **filters: object
    ) -> "OauthToken": ...

    @abstractmethod
    async def one_fresh(self, id: "UUID") -> "OauthToken":
        """The row as currently committed, bypassing anything cached in the session."""
        ...

    @abstractmethod
    async def add(self, obj: "OauthToken") -> "OauthToken": ...

    @abstractmethod
    async def update(self, obj: "OauthToken") -> "OauthToken": ...
