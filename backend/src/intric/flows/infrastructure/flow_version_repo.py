from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import FlowTemplateAssets, FlowVersions
from intric.flows.domain.flow import FlowPersistedJsonObject, FlowVersion
from intric.flows.flow_factory import FlowFactory
from intric.flows.published_definition import (
    PublishedTemplateIdentityAuditResult,
    PublishedTemplateIdentityAuditSnapshot,
    PublishedTemplateIdentityLiveAsset,
    PublishedTemplateReferenceScan,
    audit_published_template_identity_readiness,
    merge_published_template_reference_scans,
    published_definition_checksum,
    scan_published_template_references,
)
from intric.main.exceptions import NotFoundException


async def scan_flow_version_template_references(
    session: AsyncSession,
    *,
    flow_id: UUID,
    tenant_id: UUID,
) -> PublishedTemplateReferenceScan:
    stmt = (
        sa.select(FlowVersions.definition_json)
        .where(FlowVersions.flow_id == flow_id)
        .where(FlowVersions.tenant_id == tenant_id)
        .order_by(FlowVersions.version.desc())
    )
    definitions = (await session.execute(stmt)).scalars().all()
    return merge_published_template_reference_scans(
        scan_published_template_references(item) for item in definitions
    )


async def audit_flow_version_template_identity_readiness(
    session: AsyncSession,
    *,
    sample_limit: int = 50,
) -> PublishedTemplateIdentityAuditResult:
    definition_stmt = sa.select(
        FlowVersions.tenant_id,
        FlowVersions.flow_id,
        FlowVersions.version,
        FlowVersions.definition_json,
    ).order_by(
        FlowVersions.tenant_id,
        FlowVersions.flow_id,
        FlowVersions.version,
    )
    definition_rows = (await session.execute(definition_stmt)).tuples().all()

    asset_stmt = (
        sa.select(
            FlowTemplateAssets.tenant_id,
            FlowTemplateAssets.flow_id,
            FlowTemplateAssets.id,
            FlowTemplateAssets.file_id,
            Files.checksum,
        )
        .join(Files, Files.id == FlowTemplateAssets.file_id)
        .where(FlowTemplateAssets.deleted_at.is_(None))
        .order_by(
            FlowTemplateAssets.tenant_id,
            FlowTemplateAssets.flow_id,
            FlowTemplateAssets.file_id,
            FlowTemplateAssets.id,
        )
    )
    asset_rows = (await session.execute(asset_stmt)).tuples().all()

    return audit_published_template_identity_readiness(
        snapshots=(
            PublishedTemplateIdentityAuditSnapshot(
                tenant_id=tenant_id,
                flow_id=flow_id,
                version=version,
                definition_json=definition_json,
            )
            for tenant_id, flow_id, version, definition_json in definition_rows
        ),
        live_assets=(
            PublishedTemplateIdentityLiveAsset(
                tenant_id=tenant_id,
                flow_id=flow_id,
                asset_id=asset_id,
                file_id=file_id,
                checksum=file_checksum,
            )
            for tenant_id, flow_id, asset_id, file_id, file_checksum in asset_rows
        ),
        sample_limit=sample_limit,
    )


class FlowVersionRepository:
    """Tenant-scoped repository for immutable flow definition snapshots."""

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    async def create(
        self,
        flow_id: UUID,
        version: int,
        definition_json: FlowPersistedJsonObject,
        tenant_id: UUID,
    ) -> FlowVersion:
        """Persist a snapshot with checksum derived from the exact inserted payload."""
        definition_checksum = published_definition_checksum(definition_json)
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

    async def scan_template_references(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> PublishedTemplateReferenceScan:
        return await scan_flow_version_template_references(
            self.session,
            flow_id=flow_id,
            tenant_id=tenant_id,
        )

    async def has_template_asset_reference(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        template_asset_id: UUID,
        template_file_id: UUID,
    ) -> bool:
        scan = await self.scan_template_references(
            flow_id=flow_id,
            tenant_id=tenant_id,
        )
        return scan.may_reference(
            template_asset_id=template_asset_id,
            template_file_id=template_file_id,
        )
