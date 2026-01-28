from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from intric.database.tables.mcp_server_table import MCPServerTools as MCPServerToolsTable
from intric.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from intric.mcp_servers.domain.entities.mcp_server import MCPServerTool
from intric.mcp_servers.domain.repositories.mcp_server_tool_repo import MCPServerToolRepository
from intric.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerToolMapper

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MCPServerToolRepoImpl(
    BaseRepoImpl[MCPServerTool, MCPServerToolsTable, MCPServerToolMapper],
    MCPServerToolRepository,
):
    def __init__(self, session: "AsyncSession", mapper: MCPServerToolMapper):
        super().__init__(session=session, model=MCPServerToolsTable, mapper=mapper)

    async def all(self) -> list[MCPServerTool]:
        query = select(self._db_model)
        result = await self.session.scalars(query)
        result = result.all()
        if not result:
            return []

        return self.mapper.to_entities(result)

    async def by_server(self, mcp_server_id: UUID) -> list[MCPServerTool]:
        """Get all tools for a specific MCP server, ordered by name."""
        query = (
            select(self._db_model)
            .where(self._db_model.mcp_server_id == mcp_server_id)
            .order_by(self._db_model.name)
        )
        result = await self.session.scalars(query)
        result = result.all()
        if not result:
            return []

        return self.mapper.to_entities(result)

    async def find_by_name(self, mcp_server_id: UUID, name: str) -> MCPServerTool | None:
        """Find a tool by server ID and name."""
        query = select(self._db_model).where(
            sa.and_(
                self._db_model.mcp_server_id == mcp_server_id,
                self._db_model.name == name
            )
        )
        result = await self.session.scalar(query)
        if not result:
            return None

        return self.mapper.to_entity(result)

    async def add_many(self, objs: list[MCPServerTool]) -> list[MCPServerTool]:
        """Add multiple tools at once (bulk operation)."""
        if not objs:
            return []

        db_dicts = [self.mapper.to_db_dict(obj) for obj in objs]

        stmt = insert(self._db_model).values(db_dicts).returning(self._db_model)
        result = await self.session.scalars(stmt)
        await self.session.flush()

        tools = result.all()
        return self.mapper.to_entities(tools)

    async def upsert_by_server_and_name(self, obj: MCPServerTool) -> MCPServerTool:
        """Upsert a tool (update if exists by server+name, insert otherwise)."""
        db_dict = self.mapper.to_db_dict(obj)

        # PostgreSQL INSERT ... ON CONFLICT DO UPDATE
        stmt = (
            insert(self._db_model)
            .values(db_dict)
            .on_conflict_do_update(
                index_elements=['mcp_server_id', 'name'],
                set_={
                    'description': db_dict['description'],
                    'input_schema': db_dict['input_schema'],
                    'is_enabled_by_default': db_dict['is_enabled_by_default'],
                }
            )
            .returning(self._db_model)
        )

        result = await self.session.scalar(stmt)
        await self.session.flush()

        return self.mapper.to_entity(result)

    async def delete_by_server(self, mcp_server_id: UUID) -> None:
        """Delete all tools for a specific MCP server."""
        stmt = sa.delete(self._db_model).where(
            self._db_model.mcp_server_id == mcp_server_id
        )
        await self.session.execute(stmt)
        await self.session.flush()
