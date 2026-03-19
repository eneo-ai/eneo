from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional
from uuid import UUID

if TYPE_CHECKING:
    from intric.base.base_entity import Entity


class BaseRepository(ABC):
    @abstractmethod
    async def all(self) -> list["Entity"]: ...

    @abstractmethod
    async def one(self, id: UUID) -> "Entity": ...

    @abstractmethod
    async def one_or_none(self, id: UUID) -> Optional["Entity"]: ...

    @abstractmethod
    async def add(self, entity: "Entity") -> "Entity": ...

    @abstractmethod
    async def update(self, entity: "Entity") -> "Entity": ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...
