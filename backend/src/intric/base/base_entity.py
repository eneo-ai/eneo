from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Sequence, TypeVar
from uuid import UUID, uuid4

from intric.main.models import ResourcePermission

if TYPE_CHECKING:
    from intric.database.tables.base_class import BasePublic as BaseDBModel

T = TypeVar("T", bound="Entity")
DB = TypeVar("DB", bound="BaseDBModel")


class Entity:
    def __init__(
        self,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        self.id = id if id else uuid4()
        self.created_at = created_at
        self.updated_at = updated_at

        self._permissions: Optional[list[ResourcePermission]] = None

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Entity):
            return False

        # Only compare fields that are not datetime
        self_vars = {k: v for k, v in vars(self).items() if k not in ["created_at", "updated_at"]}
        other_vars = {k: v for k, v in vars(other).items() if k not in ["created_at", "updated_at"]}

        return self_vars == other_vars

    @classmethod
    def create(cls, **kwargs) -> T: ...

    @classmethod
    def to_domain(cls, db_model: DB) -> T: ...

    @property
    def is_new(self):
        return self.created_at is None

    @property
    def permissions(self) -> list[ResourcePermission]:
        if self._permissions is None:
            return [ResourcePermission.READ]

        return self._permissions

    @permissions.setter
    def permissions(self, permissions: list[ResourcePermission]):
        self._permissions = permissions


class EntityFactory(Protocol[T, DB]):
    @classmethod
    def create_entity(cls, record: DB) -> T: ...
    @classmethod
    def create_entities(cls, records: Sequence[DB]) -> List[T]: ...


class EntityMapper(Protocol[T, DB]):
    def to_db_dict(self, entity: T) -> Dict[str, Any]: ...
    def to_entity(self, db_model: DB) -> T: ...
    def to_entities(self, db_models: Sequence[DB]) -> List[T]: ...
