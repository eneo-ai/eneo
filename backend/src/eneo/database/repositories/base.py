from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.base import ExecutableOption

from eneo.database.tables.base_class import Base
from eneo.main.models import ModelId

T_Model = TypeVar("T_Model", bound=BaseModel)
ConditionAttribute = InstrumentedAttribute[Any]
Conditions = Mapping[ConditionAttribute, object]


@dataclass
class RelationshipOption:
    name: str
    table: type[Base]
    options: Sequence[Any] = ()


class BaseRepository:
    def __init__(self, session: AsyncSession):
        super().__init__()
        self.session = session


class BaseRepositoryDelegate(Generic[T_Model]):
    def __init__(
        self,
        session: AsyncSession,
        table: type[Base],
        in_db_model: type[T_Model],
        with_options: Sequence[ExecutableOption] | None = None,
    ):
        super().__init__()
        self.session = session
        self.table = table
        self.in_db_model = in_db_model
        self.with_options = list(with_options or [])

    async def get_record_from_query(self, query: Any) -> Any | None:
        for option in self.with_options:
            query = query.options(option)

        return await self.session.scalar(query)

    async def get_records_from_query(self, query: Any) -> Iterable[Any]:
        for option in self.with_options:
            query = query.options(option)

        return await self.session.scalars(query)

    async def get_model_from_query(self, query: Any) -> T_Model | None:
        record = await self.get_record_from_query(query=query)

        if record is None:
            return None

        return self.in_db_model.model_validate(record)

    async def get_models_from_query(
        self, query: sa.Select[tuple[Any]]
    ) -> list[T_Model]:
        records = await self.get_records_from_query(query=query)

        return [self.in_db_model.model_validate(record) for record in records]

    async def add(
        self,
        upsert_entry: BaseModel,
        *,
        exclude: set[str] | None = None,
        relationships: Sequence[RelationshipOption] | None = None,
        **extra_kwargs: object,
    ) -> T_Model:
        relationship_names = self._get_relationships_names()
        query = (
            sa.insert(self.table)
            .values(
                **upsert_entry.model_dump(
                    exclude_none=True,
                    exclude=(exclude or set()) | relationship_names,
                ),
                **extra_kwargs,
            )
            .returning(self.table)
        )

        for option in self.with_options:
            query = query.options(option)

        entry_in_db = await self.session.scalar(query)
        if entry_in_db is None:
            raise ValueError(
                f"Insert into {self.table.__name__} did not return a database record"
            )

        entry_in_db = await self._assign_relationships(
            entry_in_db=entry_in_db,
            new_entry=upsert_entry,
            relationships=relationships or [],
        )

        return self.in_db_model.model_validate(entry_in_db)

    def _get_query_for_related(
        self, table: type[Base], id_list: Sequence[ModelId]
    ) -> sa.Select[tuple[Base]]:
        _ids = [item.id for item in id_list]

        return sa.select(table).filter(table.id.in_(_ids))  # type: ignore[attr-defined]

    async def _get_related(
        self,
        table: type[Base],
        id_list: Sequence[ModelId],
        options: Sequence[ExecutableOption] | None = None,
    ) -> list[Base]:
        query = self._get_query_for_related(table=table, id_list=id_list)

        for option in options or []:
            query = query.options(option)

        items = await self.session.scalars(query)

        return list(items.all())

    async def _assign_relationships(
        self,
        entry_in_db: Base,
        new_entry: BaseModel,
        relationships: Sequence[RelationshipOption],
    ) -> Base:
        for relationship in relationships:
            if relationship.name in new_entry.model_fields_set:
                items = await self._get_related(
                    table=relationship.table,
                    id_list=getattr(new_entry, relationship.name),
                    options=relationship.options,
                )
                setattr(entry_in_db, relationship.name, items)
        return entry_in_db

    def _get_relationships_names(self):
        mapper = inspect(self.table)
        assert mapper is not None
        return {key for key in mapper.relationships.keys()}

    def _get_query_with_conditions(
        self, conditions: Conditions
    ) -> sa.Select[tuple[Base]]:
        query = sa.select(self.table).order_by(self.table.created_at)  # type: ignore[attr-defined]

        for attr in conditions.keys():
            query = query.where(attr == conditions[attr])

        return query

    async def get_by(self, conditions: Conditions) -> T_Model | None:
        query = self._get_query_with_conditions(conditions)

        return await self.get_model_from_query(query)

    async def filter_by(self, conditions: Conditions) -> list[T_Model]:
        query = self._get_query_with_conditions(conditions)

        return await self.get_models_from_query(query)

    async def update(
        self,
        new_entry: BaseModel,
        *,
        exclude: set[str] | None = None,
        relationships: Sequence[RelationshipOption] | None = None,
        **extra_kwargs: object,
    ) -> T_Model | None:
        relationship_names = self._get_relationships_names()
        query = (
            sa.update(self.table)
            .values(
                **new_entry.model_dump(
                    exclude_unset=True,
                    exclude={"id", "uuid"} | (exclude or set()) | relationship_names,
                ),
                **extra_kwargs,
            )
            .where(self.table.id == new_entry.id)  # type: ignore[attr-defined]
            .returning(self.table)
        )

        for option in self.with_options:
            query = query.options(option)

        entry_in_db = await self.session.scalar(query)

        if entry_in_db is None:
            return None

        entry_in_db = await self._assign_relationships(
            entry_in_db=entry_in_db,
            new_entry=new_entry,
            relationships=relationships or [],
        )

        return self.in_db_model.model_validate(entry_in_db)

    async def get(self, id: UUID, user_id: UUID | None = None) -> T_Model | None:
        query = sa.select(self.table).where(self.table.id == id)  # type: ignore[attr-defined]

        if user_id is not None:
            query = query.where(self.table.user_id == user_id)  # type: ignore[attr-defined]

        return await self.get_model_from_query(query)

    async def delete_by(self, conditions: Conditions) -> T_Model | None:
        query = sa.delete(self.table).returning(self.table)

        for attr in conditions.keys():
            query = query.where(attr == conditions[attr])

        return await self.get_model_from_query(query)

    async def delete(self, id: UUID) -> T_Model | None:
        return await self.delete_by(conditions={self.table.id: id})  # type: ignore[attr-defined]

    async def get_all(self) -> list[T_Model]:
        query = sa.select(self.table).order_by(self.table.created_at)  # type: ignore[attr-defined]

        return await self.get_models_from_query(query)

    async def get_by_ids(self, ids: list[UUID]) -> list[T_Model]:
        query = (
            sa.select(self.table)
            .where(self.table.id.in_(ids))  # type: ignore[attr-defined]
            .order_by(self.table.created_at)  # type: ignore[attr-defined]
        )

        return await self.get_models_from_query(query)
