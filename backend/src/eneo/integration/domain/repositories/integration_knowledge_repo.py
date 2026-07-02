from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )


class IntegrationKnowledgeRepository(ABC):
    @abstractmethod
    async def one_or_none(
        self, id: "UUID | None" = None, **filters: object
    ) -> "IntegrationKnowledge | None": ...

    @abstractmethod
    async def one(
        self, id: "UUID | None" = None, **filters: object
    ) -> "IntegrationKnowledge": ...

    @abstractmethod
    async def add(self, obj: "IntegrationKnowledge") -> "IntegrationKnowledge": ...

    @abstractmethod
    async def get_by_ids(self, ids: list["UUID"]) -> list["IntegrationKnowledge"]: ...

    @abstractmethod
    async def remove(self, id: "UUID") -> None: ...

    @abstractmethod
    async def update(self, obj: "IntegrationKnowledge") -> "IntegrationKnowledge": ...
