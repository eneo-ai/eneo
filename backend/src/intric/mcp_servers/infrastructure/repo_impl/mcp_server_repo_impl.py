from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from intric.database.tables.mcp_server_table import MCPServers as MCPServersTable
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from intric.mcp_servers.domain.entities.mcp_server import MCPServer
from intric.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
from intric.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MCPServerRepoImpl(
    BaseRepoImpl[MCPServer, MCPServersTable, MCPServerMapper],
    MCPServerRepository,
):
    def __init__(self, session: "AsyncSession", mapper: MCPServerMapper):
        super().__init__(session=session, model=MCPServersTable, mapper=mapper)

    async def all(self) -> list[MCPServer]:
        query = select(self._db_model)
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    async def query(  # type: ignore[override]
        self, tags: list[str] | None = None, **filters: object
    ) -> list[MCPServer]:
        """Query MCP servers with optional tag filtering."""
        query = select(self._db_model)

        if tags:
            # Filter by tags using JSONB contains operator
            query = query.where(
                sa.or_(*[self._db_model.tags.contains([tag]) for tag in tags])  # type: ignore[union-attr]
            )

        if filters:
            query = query.filter_by(**filters)

        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    async def query_by_tenant(self, tenant_id: UUID) -> list[MCPServer]:
        """Get all MCP servers for a specific tenant with tools loaded."""
        query = (
            select(self._db_model)
            .where(self._db_model.tenant_id == tenant_id)
            .options(selectinload(self._db_model.tools))
        )
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)
