from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Sequence, TypeVar
from uuid import UUID, uuid4

from typing_extensions import override

from eneo.main.models import ResourcePermission

if TYPE_CHECKING:
    from eneo.database.tables.base_class import BasePublic as BaseDBModel

T = TypeVar("T", bound="Entity")
DB = TypeVar("DB", bound="BaseDBModel")
_DB_contra = TypeVar("_DB_contra", bound="BaseDBModel", contravariant=True)  # type: ignore[misc]  # contravariant TypeVar for Protocol


class Entity:
    def __init__(
        self,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        super().__init__()
        self.id = id if id else uuid4()
        self.created_at = created_at
        self.updated_at = updated_at

        self._permissions: Optional[list[ResourcePermission]] = None

    @override
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            return False

        # Only compare fields that are not datetime
        self_vars = {
            k: v for k, v in vars(self).items() if k not in ["created_at", "updated_at"]
        }
        other_vars = {
            k: v
            for k, v in vars(other).items()
            if k not in ["created_at", "updated_at"]
        }

        return self_vars == other_vars

    @classmethod
    def create(cls, *args: object, **kwargs: object) -> "T": ...  # type: ignore[misc]  # variadic *args/**kwargs on classmethod returning TypeVar

    @classmethod
    def to_domain(cls, db_model: "DB", *args: object, **kwargs: object) -> "T": ...  # type: ignore[misc]  # variadic *args/**kwargs on classmethod returning TypeVar

    @property
    def is_new(self) -> bool:
        return self.created_at is None

    @property
    def permissions(self) -> list[ResourcePermission]:
        if self._permissions is None:
            return [ResourcePermission.READ]

        return self._permissions

    @permissions.setter
    def permissions(self, permissions: list[ResourcePermission]) -> None:
        self._permissions = permissions


class EntityFactory(Protocol[T, _DB_contra]):
    @classmethod
    def create_entity(cls, record: _DB_contra) -> T: ...
    @classmethod
    def create_entities(cls, records: Sequence[_DB_contra]) -> List[T]: ...


class EntityMapper(Protocol[T, _DB_contra]):
    def to_db_dict(self, entity: T) -> Dict[str, Any]: ...
    def to_entity(self, db_model: _DB_contra) -> T: ...
    def to_entities(self, db_models: Sequence[_DB_contra]) -> List[T]: ...
