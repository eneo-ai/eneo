from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing_extensions import override

from intric.database.tables.mcp_server_table import MCPServers as MCPServersTable
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
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

    @override
    async def all(self) -> list[MCPServer]:
        query = select(self._db_model)
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    async def query(  # type: ignore[override]
        self,
        tags: list[str] | None = None,
        include_space_scoped: bool = False,
        **filters: object,
    ) -> list[MCPServer]:
        """Query MCP servers with optional tag filtering.

        By default returns tenant-wide entries only (``space_id IS NULL``).
        Pass ``include_space_scoped=True`` to also return space-private rows
        (used by the space-scoped catalog/listing endpoints).
        """
        query = select(self._db_model)

        if tags:
            # Filter by tags using JSONB contains operator
            query = query.where(
                sa.or_(*[self._db_model.tags.contains([tag]) for tag in tags])  # type: ignore[union-attr]
            )

        if filters:
            query = query.filter_by(**filters)

        if not include_space_scoped:
            query = query.where(self._db_model.space_id.is_(None))

        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    @override
    async def query_by_tenant(self, tenant_id: UUID) -> list[MCPServer]:
        """Get tenant-wide MCP servers for a tenant with tools loaded.

        Excludes space-private entries (``space_id IS NOT NULL``); those are
        only visible inside their owning space.
        """
        query = (
            select(self._db_model)
            .where(self._db_model.tenant_id == tenant_id)
            .where(self._db_model.space_id.is_(None))
            .options(
                selectinload(self._db_model.tools),
                selectinload(self._db_model.security_classification).selectinload(
                    SecurityClassificationDBModel.tenant
                ),
            )
        )
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)

    async def query_by_space(self, tenant_id: UUID, space_id: UUID) -> list[MCPServer]:
        """Get space-private MCP servers owned by a given space."""
        query = (
            select(self._db_model)
            .where(self._db_model.tenant_id == tenant_id)
            .where(self._db_model.space_id == space_id)
            .options(
                selectinload(self._db_model.tools),
                selectinload(self._db_model.security_classification).selectinload(
                    SecurityClassificationDBModel.tenant
                ),
            )
        )
        result = await self.session.scalars(query)
        records = result.all()
        if not records:
            return []

        return self.mapper.to_entities(records)
