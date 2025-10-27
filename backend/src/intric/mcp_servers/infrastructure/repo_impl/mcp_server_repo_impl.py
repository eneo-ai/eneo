from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.future import select

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
        result = result.all()
        if not result:
            return []

        return self.mapper.to_entities(result)

    async def query(self, tags: list[str] | None = None) -> list[MCPServer]:
        """Query MCP servers with optional tag filtering."""
        query = select(self._db_model)

        if tags:
            # Filter by tags using JSONB contains operator
            query = query.where(
                sa.or_(*[self._db_model.tags.contains([tag]) for tag in tags])
            )

        result = await self.session.scalars(query)
        result = result.all()
        if not result:
            return []

        return self.mapper.to_entities(result)
