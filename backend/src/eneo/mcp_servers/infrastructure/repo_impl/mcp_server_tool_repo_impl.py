import asyncio
import json
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing_extensions import override

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import (
    MCPServers as MCPServersTable,
)
from eneo.database.tables.mcp_server_table import (
    MCPServerTools as MCPServerToolsTable,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServerTool,
    MCPToolCatalogLimitExceeded,
    MCPToolCatalogStagingTimeout,
)
from eneo.mcp_servers.domain.repositories.mcp_server_tool_repo import (
    MCPServerToolRepository,
)
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
    MCPServerToolMapper,
)


def _persisted_tool_size_bytes(tool: MCPServerTool) -> int:
    """Measure attacker-controlled fields retained for active and pending review."""
    return len(
        json.dumps(
            {
                "name": tool.name,
                "title": tool.title,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "pending_description": tool.pending_description,
                "pending_input_schema": tool.pending_input_schema,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


MCP_TOOL_CATALOG_STAGE_TIMEOUT_SECONDS = 2.0


class MCPServerToolRepoImpl(
    BaseRepoImpl[MCPServerTool, MCPServerToolsTable, MCPServerToolMapper],
    MCPServerToolRepository,
):
    def __init__(self, session: "AsyncSession", mapper: MCPServerToolMapper):
        super().__init__(session=session, model=MCPServerToolsTable, mapper=mapper)

    @override
    async def all(self) -> list[MCPServerTool]:
        query = select(self._db_model)
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    @override
    async def by_server(self, mcp_server_id: UUID) -> list[MCPServerTool]:
        """Get all tools for a specific MCP server, ordered by name."""
        query = (
            select(self._db_model)
            .where(self._db_model.mcp_server_id == mcp_server_id)
            .order_by(self._db_model.name)
        )
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    @override
    async def find_by_name(
        self, mcp_server_id: UUID, name: str
    ) -> MCPServerTool | None:
        """Find a tool by server ID and name."""
        query = select(self._db_model).where(
            sa.and_(
                self._db_model.mcp_server_id == mcp_server_id,
                self._db_model.name == name,
            )
        )
        result = await self.session.scalar(query)
        if not result:
            return None

        return self.mapper.to_entity(result)

    @override
    async def add_many(self, objs: list[MCPServerTool]) -> list[MCPServerTool]:
        """Add multiple tools at once (bulk operation)."""
        if not objs:
            return []

        db_dicts = [self.mapper.to_db_dict(obj) for obj in objs]

        stmt = insert(self._db_model).values(db_dicts).returning(self._db_model)
        result = await self.session.scalars(stmt)
        await self.session.flush()

        records = result.all()
        return self.mapper.to_entities(records)

    @override
    async def stage_observed(self, objs: list[MCPServerTool]) -> list[MCPServerTool]:
        """Durably stage one bounded live catalog in a short transaction.

        Existing pending reviews win over later observations. An approved row
        is updated only when its active description or schema differs from the
        live definition; active fields remain untouched until approval. The
        independent transaction releases the per-server lock before model
        preparation begins and keeps an observed review item if that later
        request work rolls back.
        """
        if not objs:
            return []

        try:
            # Runtime discovery is called inside a request transaction. A
            # separate short transaction keeps the server-row mutex out of the
            # model request, while this deadline prevents pool exhaustion or a
            # future conflicting outer write lock from stalling the chat.
            async with asyncio.timeout(MCP_TOOL_CATALOG_STAGE_TIMEOUT_SECONDS):
                async with sessionmanager.session() as session, session.begin():
                    return await self._stage_observed_in_transaction(session, objs)
        except TimeoutError as exc:
            raise MCPToolCatalogStagingTimeout(
                "Timed out staging the observed MCP tool catalog"
            ) from exc

    async def _stage_observed_in_transaction(
        self, session: AsyncSession, objs: list[MCPServerTool]
    ) -> list[MCPServerTool]:
        """Check the projected union and write it while holding one server lock."""

        server_id = objs[0].mcp_server_id
        if any(obj.mcp_server_id != server_id for obj in objs):
            raise ValueError("Observed tools must belong to one MCP server")
        observed_names = [obj.name for obj in objs]
        if len(observed_names) != len(set(observed_names)):
            raise ValueError("Observed tools must have unique names")

        # The server row is the per-catalog mutex. Every runtime observation
        # for one server is serialized through this lock, so the projected
        # union is checked against committed predecessors before any insert.
        limits = (
            await session.execute(
                select(
                    MCPServersTable.tool_catalog_max_count,
                    MCPServersTable.tool_catalog_max_bytes,
                )
                .where(MCPServersTable.id == server_id)
                .with_for_update()
            )
        ).one_or_none()
        if limits is None:
            raise ValueError("MCP server not found for observed tool catalog")

        existing_records = (
            await session.scalars(
                select(self._db_model)
                .where(self._db_model.mcp_server_id == server_id)
                .with_for_update()
            )
        ).all()
        projected = {
            tool.name: tool for tool in self.mapper.to_entities(existing_records)
        }
        for observed in objs:
            existing = projected.get(observed.name)
            if existing is None:
                projected[observed.name] = observed
                continue
            if existing.requires_approval:
                continue
            if (
                existing.description == observed.pending_description
                and existing.input_schema == observed.pending_input_schema
            ):
                continue
            existing.pending_description = observed.pending_description
            existing.pending_input_schema = observed.pending_input_schema
            existing.requires_approval = True
            existing.removed_from_remote = False

        max_count, max_bytes = limits
        projected_bytes = sum(
            _persisted_tool_size_bytes(tool) for tool in projected.values()
        )
        if len(projected) > max_count or projected_bytes > max_bytes:
            raise MCPToolCatalogLimitExceeded(
                "Projected persisted tool catalog exceeds the configured "
                f"limits ({max_count} definitions, {max_bytes} bytes)"
            )

        db_dicts = [self.mapper.to_db_dict(obj) for obj in objs]
        excluded = insert(self._db_model).excluded
        stmt = (
            insert(self._db_model)
            .values(db_dicts)
            .on_conflict_do_update(
                index_elements=["mcp_server_id", "name"],
                set_={
                    "pending_description": excluded.pending_description,
                    "pending_input_schema": excluded.pending_input_schema,
                    "requires_approval": True,
                    "removed_from_remote": False,
                },
                where=sa.and_(
                    self._db_model.requires_approval.is_(False),
                    sa.or_(
                        self._db_model.description.is_distinct_from(
                            excluded.pending_description
                        ),
                        self._db_model.input_schema.is_distinct_from(
                            excluded.pending_input_schema
                        ),
                    ),
                ),
            )
            .returning(self._db_model)
        )
        result = await session.scalars(stmt)
        await session.flush()
        return self.mapper.to_entities(result.all())

    @override
    async def upsert_by_server_and_name(self, obj: MCPServerTool) -> MCPServerTool:
        """Upsert a tool (update if exists by server+name, insert otherwise)."""
        db_dict = self.mapper.to_db_dict(obj)

        # PostgreSQL INSERT ... ON CONFLICT DO UPDATE
        stmt = (
            insert(self._db_model)
            .values(db_dict)
            .on_conflict_do_update(
                index_elements=["mcp_server_id", "name"],
                set_={
                    "title": db_dict["title"],
                    "description": db_dict["description"],
                    "input_schema": db_dict["input_schema"],
                    "is_enabled_by_default": db_dict["is_enabled_by_default"],
                },
            )
            .returning(self._db_model)
        )

        record = await self.session.scalar(stmt)
        await self.session.flush()

        if record is None:
            raise ValueError("Failed to upsert MCP server tool")
        return self.mapper.to_entity(record)

    @override
    async def delete_by_server(self, mcp_server_id: UUID) -> None:
        """Delete all tools for a specific MCP server."""
        stmt = sa.delete(self._db_model).where(
            self._db_model.mcp_server_id == mcp_server_id
        )
        await self.session.execute(stmt)
        await self.session.flush()
