from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import FlowVersions
from intric.flows.flow import FlowVersion, JsonObject
from intric.flows.flow_factory import FlowFactory
from intric.main.exceptions import NotFoundException


class FlowVersionRepository:
    """Tenant-scoped repository for immutable flow definition snapshots."""

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    async def create(
        self,
        flow_id: UUID,
        version: int,
        definition_checksum: str,
        definition_json: JsonObject,
        tenant_id: UUID,
    ) -> FlowVersion:
        stmt = (
            sa.insert(FlowVersions)
            .values(
                flow_id=flow_id,
                version=version,
                tenant_id=tenant_id,
                definition_checksum=definition_checksum,
                definition_json=definition_json,
            )
            .returning(FlowVersions)
        )
        version_in_db = await self.session.scalar(stmt)
        if version_in_db is None:
            raise NotFoundException("Could not create flow version.")
        return self.factory.from_flow_version_db(version_in_db)

    async def get(self, flow_id: UUID, version: int, tenant_id: UUID) -> FlowVersion:
        stmt = (
            sa.select(FlowVersions)
            .where(FlowVersions.flow_id == flow_id)
            .where(FlowVersions.version == version)
            .where(FlowVersions.tenant_id == tenant_id)
        )
        version_in_db = await self.session.scalar(stmt)
        if version_in_db is None:
            raise NotFoundException("Flow version not found.")
        return self.factory.from_flow_version_db(version_in_db)

    async def get_latest(self, flow_id: UUID, tenant_id: UUID) -> FlowVersion | None:
        stmt = (
            sa.select(FlowVersions)
            .where(FlowVersions.flow_id == flow_id)
            .where(FlowVersions.tenant_id == tenant_id)
            .order_by(FlowVersions.version.desc())
            .limit(1)
        )
        version_in_db = await self.session.scalar(stmt)
        if version_in_db is None:
            return None
        return self.factory.from_flow_version_db(version_in_db)

    async def list_versions(self, flow_id: UUID, tenant_id: UUID) -> list[FlowVersion]:
        stmt = (
            sa.select(FlowVersions)
            .where(FlowVersions.flow_id == flow_id)
            .where(FlowVersions.tenant_id == tenant_id)
            .order_by(FlowVersions.version.desc())
        )
        versions = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_version_db(item) for item in versions]
