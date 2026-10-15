from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )


@dataclass(frozen=True)
class IntegrationKnowledgePlacement:
    """The space that owns an item, read from columns only."""

    integration_knowledge_id: "UUID"
    space_id: "UUID"
    space_name: str
    personal: bool
    organization: bool
    last_sync_status: str


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
    async def list_placements(
        self, tenant_id: "UUID"
    ) -> list[IntegrationKnowledgePlacement]:
        """Every item of the tenant, ordered by space name and then creation."""
        ...

    @abstractmethod
    async def remove(self, id: "UUID") -> None: ...

    @abstractmethod
    async def update(self, obj: "IntegrationKnowledge") -> "IntegrationKnowledge": ...

    @abstractmethod
    async def adjust_size(self, id: "UUID", delta: int) -> int:
        """Atomically add ``delta`` bytes (floored at zero) and return the new size.

        Several entity copies take part in one sync; a read-modify-write on any
        of them would overwrite the others' changes.
        """
        ...
