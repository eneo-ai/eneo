from typing import TYPE_CHECKING, Type
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from intric.database.tables.mcp_server_table import (
    MCPServerSettings as MCPServerSettingsTable,
)
from intric.mcp_servers.domain.entities.mcp_server import MCPServerSettings
from intric.mcp_servers.domain.repositories.mcp_server_settings_repo import (
    MCPServerSettingsRepository,
)
from intric.mcp_servers.infrastructure.mappers.mcp_server_settings_mapper import (
    MCPServerSettingsMapper,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MCPServerSettingsRepoImpl(MCPServerSettingsRepository):
    _db_model: Type[MCPServerSettingsTable] = MCPServerSettingsTable

    def __init__(self, session: "AsyncSession", mapper: MCPServerSettingsMapper):
        self.session = session
        self.mapper = mapper

    async def query(self, tenant_id: UUID) -> list[MCPServerSettings]:
        query = (
            select(self._db_model)
            .filter_by(tenant_id=tenant_id)
            .options(selectinload(self._db_model.mcp_server))  # type: ignore[arg-type]
        )
        result = await self.session.scalars(query)
        records = result.all()

        if not records:
            return []

        return self.mapper.to_entities(records)

    async def one(self, tenant_id: UUID, mcp_server_id: UUID) -> MCPServerSettings:
        result = await self.one_or_none(tenant_id, mcp_server_id)
        if not result:
            raise ValueError("MCPServerSettings not found")
        return result

    async def one_or_none(
        self, tenant_id: UUID, mcp_server_id: UUID
    ) -> MCPServerSettings | None:
        query = (
            select(self._db_model)
            .filter_by(tenant_id=tenant_id, mcp_server_id=mcp_server_id)
            .options(selectinload(self._db_model.mcp_server))  # type: ignore[arg-type]
        )
        record = await self.session.scalar(query)

        if not record:
            return None

        return self.mapper.to_entity(record)

    async def add(self, obj: MCPServerSettings) -> MCPServerSettings:
        db_dict = self.mapper.to_db_dict(obj)

        query = sa.insert(self._db_model).values(**db_dict).returning(self._db_model)
        result = await self.session.execute(query)
        _record = result.scalar_one()

        return await self.one(_record.tenant_id, _record.mcp_server_id)

    async def update(self, obj: MCPServerSettings) -> MCPServerSettings:
        db_dict = self.mapper.to_db_dict(obj)

        query = (
            sa.update(self._db_model)
            .where(
                sa.and_(
                    self._db_model.tenant_id == obj.tenant_id,
                    self._db_model.mcp_server_id == obj.mcp_server_id,
                )
            )
            .values(**db_dict)
            .returning(self._db_model)
        )

        result = await self.session.execute(query)
        _record = result.scalar_one()

        return await self.one(_record.tenant_id, _record.mcp_server_id)

    async def delete(self, tenant_id: UUID, mcp_server_id: UUID) -> None:
        stmt = sa.delete(self._db_model).where(
            sa.and_(
                self._db_model.tenant_id == tenant_id,
                self._db_model.mcp_server_id == mcp_server_id,
            )
        )
        await self.session.execute(stmt)
