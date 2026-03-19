from uuid import UUID

import sqlalchemy as sa

from intric.allowed_origins.allowed_origin_models import AllowedOriginInDB
from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.allowed_origins_table import AllowedOrigins


class AllowedOriginRepository:
    def __init__(self, session: AsyncSession):
        self.delegate: BaseRepositoryDelegate[AllowedOriginInDB] = BaseRepositoryDelegate(
            session=session, table=AllowedOrigins, in_db_model=AllowedOriginInDB
        )

    async def add_origins(self, origins: list[str], tenant_id: UUID):
        stmt = (
            sa.insert(AllowedOrigins)
            .values([dict(url=origin, tenant_id=tenant_id) for origin in origins])
            .returning(AllowedOrigins)
        )

        return await self.delegate.get_models_from_query(stmt)

    async def add_origin(self, origin: str, tenant_id: UUID):
        stmt = (
            sa.insert(AllowedOrigins)
            .values(url=origin, tenant_id=tenant_id)
            .returning(AllowedOrigins)
        )

        return await self.delegate.get_model_from_query(stmt)

    async def get_origin(self, origin: str):
        stmt = sa.select(AllowedOrigins).where(AllowedOrigins.url == origin)

        return await self.delegate.get_model_from_query(stmt)

    async def get_all(self):
        return await self.delegate.get_all()

    async def get_by_tenant(self, tenant_id: UUID):
        return await self.delegate.filter_by(
            conditions={AllowedOrigins.tenant_id: tenant_id}
        )

    async def delete(self, id: UUID):
        return await self.delegate.delete(id)
