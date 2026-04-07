from dataclasses import dataclass, field
from typing import Any, Type
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.base import ExecutableOption

from intric.database.tables.base_class import Base
from intric.main.models import ModelId


@dataclass
class RelationshipOption:
    name: str
    table: Base
    options: list[ExecutableOption] = field(default_factory=list)


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


class BaseRepositoryDelegate:
    def __init__(
        self,
        session: AsyncSession,
        table: Type[Base],
        in_db_model: Type[BaseModel],
        with_options: list = [],
    ):
        self.session = session
        self.table = table
        self.in_db_model = in_db_model
        self.with_options = with_options

    async def get_record_from_query(self, query):
        for option in self.with_options:
            query = query.options(option)

        return await self.session.scalar(query)

    async def get_records_from_query(self, query):
        for option in self.with_options:
            query = query.options(option)

        return await self.session.scalars(query)

    async def get_model_from_query(self, query):
        record = await self.get_record_from_query(query=query)

        if record is None:
            return

        return self.in_db_model.model_validate(record)

    async def get_models_from_query(self, query: sa.Select):
        records = await self.get_records_from_query(query=query)

        return [self.in_db_model.model_validate(record) for record in records]

    async def add(
        self,
        upsert_entry: BaseModel,
        *,
        exclude: set = set(),
        relationships: list[RelationshipOption] = [],
        **extra_kwargs,
    ):
        query = (
            sa.insert(self.table)
            .values(
                **upsert_entry.model_dump(
                    exclude_none=True,
                    exclude=exclude | self._get_relationships_names(),
                ),
                **extra_kwargs,
            )
            .returning(self.table)
        )

        for option in self.with_options:
            query = query.options(option)

        entry_in_db = await self.session.scalar(query)

        entry_in_db = await self._assign_relationships(
            entry_in_db=entry_in_db,
            new_entry=upsert_entry,
            relationships=relationships,
        )

        return self.in_db_model.model_validate(entry_in_db)

    def _get_query_for_related(self, table: Type[Base], id_list: list[ModelId]):
        _ids = [item.id for item in id_list]

        return sa.select(table).filter(table.id.in_(_ids))

    async def _get_related(
        self,
        table: Type[Base],
        id_list: list[ModelId],
        options: list[ExecutableOption] = [],
    ):
        query = self._get_query_for_related(table=table, id_list=id_list)

        for option in options:
            query = query.options(option)

        items = await self.session.scalars(query)

        return items.all()

    async def _assign_relationships(
        self,
        entry_in_db: Base,
        new_entry: BaseModel,
        relationships: list[RelationshipOption] = [],
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
        return {key for key in inspect(self.table).relationships.keys()}

    def _get_query_with_conditions(self, conditions: dict[InstrumentedAttribute, Any]):
        query = sa.select(self.table).order_by(self.table.created_at)

        for attr in conditions.keys():
            query = query.where(attr == conditions[attr])

        return query

    async def get_by(self, conditions: dict[InstrumentedAttribute, Any]):
        query = self._get_query_with_conditions(conditions)

        return await self.get_model_from_query(query)

    async def filter_by(self, conditions: dict[InstrumentedAttribute, Any]):
        query = self._get_query_with_conditions(conditions)

        return await self.get_models_from_query(query)

    async def update(
        self,
        new_entry: BaseModel,
        *,
        exclude: set = set(),
        relationships: list[RelationshipOption] = [],
        **extra_kwargs,
    ):
        query = (
            sa.update(self.table)
            .values(
                **new_entry.model_dump(
                    exclude_unset=True,
                    exclude={"id", "uuid"} | exclude | self._get_relationships_names(),
                ),
                **extra_kwargs,
            )
            .where(self.table.id == new_entry.id)
            .returning(self.table)
        )

        for option in self.with_options:
            query = query.options(option)

        entry_in_db = await self.session.scalar(query)

        if entry_in_db is None:
            return

        entry_in_db = await self._assign_relationships(
            entry_in_db=entry_in_db,
            new_entry=new_entry,
            relationships=relationships,
        )

        return self.in_db_model.model_validate(entry_in_db)

    async def get(self, id: UUID, user_id: UUID = None):
        query = sa.select(self.table).where(self.table.id == id)

        if user_id is not None:
            query = query.where(self.table.user_id == user_id)

        return await self.get_model_from_query(query)

    async def delete_by(self, conditions: dict[InstrumentedAttribute, Any]):
        query = sa.delete(self.table).returning(self.table)

        for attr in conditions.keys():
            query = query.where(attr == conditions[attr])

        return await self.get_model_from_query(query)

    async def delete(self, id: UUID):
        return await self.delete_by(conditions={self.table.id: id})

    async def get_all(self):
        query = sa.select(self.table).order_by(self.table.created_at)

        return await self.get_models_from_query(query)

    async def get_by_ids(self, ids: list[UUID]):
        query = (
            sa.select(self.table)
            .where(self.table.id.in_(ids))
            .order_by(self.table.created_at)
        )

        return await self.get_models_from_query(query)
