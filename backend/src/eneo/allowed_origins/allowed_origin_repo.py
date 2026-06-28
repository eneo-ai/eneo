from uuid import UUID

import sqlalchemy as sa

from eneo.allowed_origins.allowed_origin_models import AllowedOriginInDB
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.allowed_origins_table import AllowedOrigins


class AllowedOriginRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[AllowedOriginInDB] = (
            BaseRepositoryDelegate(
                session=session, table=AllowedOrigins, in_db_model=AllowedOriginInDB
            )
        )

    async def add_origins(
        self, origins: list[str], tenant_id: UUID
    ) -> list[AllowedOriginInDB]:
        stmt = (
            sa.insert(AllowedOrigins)
            .values([dict(url=origin, tenant_id=tenant_id) for origin in origins])
            .returning(AllowedOrigins)
        )
        # get_records_from_query accepts Any; validate manually to avoid Select[...] mismatch
        records = await self.delegate.get_records_from_query(stmt)
        return [AllowedOriginInDB.model_validate(r) for r in records]

    async def add_origin(
        self, origin: str, tenant_id: UUID
    ) -> AllowedOriginInDB | None:
        stmt = (
            sa.insert(AllowedOrigins)
            .values(url=origin, tenant_id=tenant_id)
            .returning(AllowedOrigins)
        )
        # get_record_from_query accepts Any; returns the ORM row directly
        record = await self.delegate.get_record_from_query(stmt)
        if record is None:
            return None
        return AllowedOriginInDB.model_validate(record)

    async def get_origin(self, origin: str) -> AllowedOriginInDB | None:
        stmt = sa.select(AllowedOrigins).where(AllowedOrigins.url == origin).limit(1)
        return await self.delegate.get_model_from_query(stmt)

    async def get_by_id(self, origin_id: UUID) -> AllowedOriginInDB | None:
        stmt = sa.select(AllowedOrigins).where(AllowedOrigins.id == origin_id).limit(1)
        return await self.delegate.get_model_from_query(stmt)

    async def get_origin_for_tenant(
        self, origin: str, tenant_id: UUID
    ) -> AllowedOriginInDB | None:
        stmt = (
            sa.select(AllowedOrigins)
            .where(AllowedOrigins.url == origin)
            .where(AllowedOrigins.tenant_id == tenant_id)
        )
        return await self.delegate.get_model_from_query(stmt)

    async def get_all(self) -> list[AllowedOriginInDB]:
        return await self.delegate.get_all()

    async def get_by_tenant(self, tenant_id: UUID) -> list[AllowedOriginInDB]:
        return await self.delegate.filter_by(
            conditions={AllowedOrigins.tenant_id: tenant_id}
        )

    async def delete(self, id: UUID):
        return await self.delegate.delete(id)
