from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing_extensions import override

from eneo.database.tables.ai_models_table import ImageModels
from eneo.database.tables.assistant_table import (
    AssistantMCPServers,
    AssistantMCPServerTools,
)
from eneo.database.tables.mcp_server_table import MCPServers as MCPServersTable
from eneo.database.tables.mcp_server_table import (
    MCPServerTools,
    MCPServerUserGroups,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.integration.infrastructure.repo_impl.base_repo_impl import BaseRepoImpl
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.mcp_servers.domain.repositories.mcp_server_repo import MCPServerRepository
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import MCPServerMapper

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def backing_model_options() -> list[Any]:
    """Loader options for the image model a built-in provider runs on.

    The model's classification and provider ride along so the mapper can
    project them without lazy loads.
    """
    return [
        selectinload(MCPServersTable.image_model).options(
            selectinload(ImageModels.provider),
            selectinload(ImageModels.security_classification).selectinload(
                SecurityClassificationDBModel.tenant
            ),
        )
    ]


class MCPServerRepoImpl(
    BaseRepoImpl[MCPServer, MCPServersTable, MCPServerMapper],
    MCPServerRepository,
):
    def __init__(self, session: "AsyncSession", mapper: MCPServerMapper):
        super().__init__(session=session, model=MCPServersTable, mapper=mapper)
        # Audience groups and the backing image model are part of the
        # provider's identity for resolution, so every single-row read
        # carries them.
        self._options = [
            selectinload(self._db_model.user_groups),
            *backing_model_options(),
        ]

    async def _sync_user_groups(self, server: MCPServer) -> None:
        """Make the audience join rows match the entity's user_group_ids."""
        await self.session.execute(
            sa.delete(MCPServerUserGroups).where(
                MCPServerUserGroups.mcp_server_id == server.id
            )
        )
        if server.user_group_ids:
            await self.session.execute(
                sa.insert(MCPServerUserGroups).values(
                    [
                        {"mcp_server_id": server.id, "user_group_id": group_id}
                        for group_id in dict.fromkeys(server.user_group_ids)
                    ]
                )
            )

    @override
    async def add(self, obj: MCPServer) -> MCPServer:
        created = await super().add(obj)
        if obj.user_groups:
            created.user_groups = list(obj.user_groups)
            await self._sync_user_groups(created)
        if obj.user_groups or obj.image_model_id is not None:
            # Re-read so the response carries the audience and the backing
            # model projection, neither of which the insert returns.
            return await self.one(id=created.id)
        return created

    @override
    async def update(self, obj: MCPServer) -> MCPServer:
        await self._sync_user_groups(obj)
        return await super().update(obj)

    @override
    async def detach_from_spaces_and_assistants(self, id: UUID) -> None:
        tool_ids = sa.select(MCPServerTools.id).where(
            MCPServerTools.mcp_server_id == id
        )
        await self.session.execute(
            sa.delete(SpacesMCPServerTools).where(
                SpacesMCPServerTools.mcp_server_tool_id.in_(tool_ids)
            )
        )
        await self.session.execute(
            sa.delete(AssistantMCPServerTools).where(
                AssistantMCPServerTools.mcp_server_tool_id.in_(tool_ids)
            )
        )
        await self.session.execute(
            sa.delete(SpacesMCPServers).where(SpacesMCPServers.mcp_server_id == id)
        )
        await self.session.execute(
            sa.delete(AssistantMCPServers).where(
                AssistantMCPServers.mcp_server_id == id
            )
        )

    @override
    async def all(self) -> list[MCPServer]:
        query = select(self._db_model).options(*self._options)
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

        # Stable order: without it Postgres returns heap order, so an updated
        # row (e.g. a provider toggle) jumps around in admin lists.
        query = query.options(*self._options).order_by(
            self._db_model.created_at, self._db_model.id
        )
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    @override
    async def query_by_tenant(self, tenant_id: UUID) -> list[MCPServer]:
        """Get all MCP servers for a specific tenant with tools loaded."""
        query = (
            select(self._db_model)
            .where(self._db_model.tenant_id == tenant_id)
            .options(
                selectinload(self._db_model.tools),
                selectinload(self._db_model.user_groups),
                selectinload(self._db_model.security_classification).selectinload(
                    SecurityClassificationDBModel.tenant
                ),
                *backing_model_options(),
            )
            .order_by(self._db_model.created_at, self._db_model.id)
        )
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)
