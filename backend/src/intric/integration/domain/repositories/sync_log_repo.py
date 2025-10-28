from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from intric.integration.domain.entities.sync_log import SyncLog


class SyncLogRepository(ABC):
    """Abstract repository for sync logs."""

    @abstractmethod
    async def add(self, obj: "SyncLog") -> "SyncLog": ...

    @abstractmethod
    async def update(self, obj: "SyncLog") -> "SyncLog": ...

    @abstractmethod
    async def get_by_id(self, sync_log_id: UUID) -> "SyncLog | None": ...

    @abstractmethod
    async def get_by_integration_knowledge(
        self, integration_knowledge_id: UUID, limit: int = 50, offset: int = 0
    ) -> list["SyncLog"]: ...

    @abstractmethod
    async def count_by_integration_knowledge(
        self, integration_knowledge_id: UUID
    ) -> int: ...

    @abstractmethod
    async def get_recent_by_integration_knowledge(
        self, integration_knowledge_id: UUID, limit: int = 10
    ) -> list["SyncLog"]: ...
