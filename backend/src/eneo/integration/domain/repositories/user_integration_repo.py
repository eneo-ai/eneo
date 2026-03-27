from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.integration.domain.entities.user_integration import UserIntegration


class UserIntegrationRepository(ABC):
    @abstractmethod
    async def query(self, **filters) -> list["UserIntegration"]: ...

    @abstractmethod
    async def one_or_none(
        self, id: "UUID | None" = None, **filters
    ) -> "UserIntegration | None": ...

    @abstractmethod
    async def one(self, id: "UUID | None" = None, **filters) -> "UserIntegration": ...

    @abstractmethod
    async def add(self, obj: "UserIntegration") -> "UserIntegration": ...

    @abstractmethod
    async def remove(self, id: "UUID") -> None: ...
