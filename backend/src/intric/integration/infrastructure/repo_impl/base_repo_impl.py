from typing import TYPE_CHECKING, Generic, Type, TypeVar

import sqlalchemy as sa
from sqlalchemy.future import select

from intric.base.base_entity import Entity, EntityMapper
from intric.database.tables.base_class import BasePublic
from intric.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


T = TypeVar("T", bound=Entity)
DB = TypeVar("DB", bound=BasePublic)
M = TypeVar("M", bound=EntityMapper)


class BaseRepoImpl(Generic[T, DB, M]):
    def __init__(self, session: "AsyncSession", model: Type[DB], mapper: M):
        self.session = session
        self._db_model = model
        self.mapper = mapper

        self._options = []

    async def query(self, **filters) -> list[T]:
        if not filters:
            return []

        query = select(self._db_model).filter_by(**filters).options(*self._options)
        result = await self.session.scalars(query)
        result = result.all()

        if not result:
            return []

        return self.mapper.to_entities(result)

    async def one_or_none(self, id: "UUID | None" = None, **filters) -> T | None:
        if not filters:
            if id is None:
                raise ValueError("No filter is specified")
            filters = {"id": id}

        query = select(self._db_model).filter_by(**filters).options(*self._options)
        record = await self.session.scalar(query)

        if not record:
            return None

        return self.mapper.to_entity(record)

    async def one(self, id: "UUID | None" = None, **filters) -> T:
        entity = await self.one_or_none(id=id, **filters)
        if not entity:
            raise NotFoundException(f"{self._db_model.__name__} not found")
        return entity

    async def add(self, obj: T) -> T:
        db_dict = self.mapper.to_db_dict(obj)

        query = sa.insert(self._db_model).values(**db_dict).returning(self._db_model)
        result = await self.session.execute(query)
        _record = result.scalar_one()

        return await self.one(id=_record.id)

    async def update(self, obj: T) -> T:
        assert not obj.is_new
        db_dict = self.mapper.to_db_dict(obj)

        query = (
            sa.update(self._db_model)
            .where(self._db_model.id == obj.id)
            .values(**db_dict)
            .returning(self._db_model)
        )

        result = await self.session.execute(query)
        _record = result.scalar_one()

        return await self.one(id=_record.id)

    async def delete(self, id: "UUID") -> None:
        stmt = sa.delete(self._db_model).where(self._db_model.id == id)
        await self.session.execute(stmt)

    async def lookup(self, keys: list) -> list[Entity]:
        if not keys:
            return []

        query = (
            select(self._db_model)
            .where(self._db_model.id.in_(keys))
            .options(*self._options)
        )
        result = await self.session.scalars(query)
        records = result.all()

        if not records:
            return []

        return self.mapper.to_entities(records)
