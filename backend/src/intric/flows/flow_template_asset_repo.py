from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession
from intric.database.tables.flow_tables import FlowTemplateAssets
from intric.database.tables.users_table import Users
from intric.flows.flow import FlowTemplateAsset
from intric.main.exceptions import NotFoundException


class FlowTemplateAssetRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        flow_id: UUID,
        space_id: UUID,
        tenant_id: UUID,
        file_id: UUID,
        name: str,
        checksum: str,
        mimetype: str | None,
        placeholders: list[str],
        created_by_user_id: UUID | None,
        updated_by_user_id: UUID | None,
        status: str = "ready",
    ) -> FlowTemplateAsset:
        row = await self.session.scalar(
            sa.insert(FlowTemplateAssets)
            .values(
                flow_id=flow_id,
                space_id=space_id,
                tenant_id=tenant_id,
                file_id=file_id,
                name=name,
                checksum=checksum,
                mimetype=mimetype,
                placeholders=placeholders,
                created_by_user_id=created_by_user_id,
                updated_by_user_id=updated_by_user_id,
                status=status,
            )
            .returning(FlowTemplateAssets)
        )
        if row is None:
            raise NotFoundException("Could not create flow template asset.")
        return await self.get(asset_id=cast(UUID, row.id), tenant_id=tenant_id)

    async def get(self, *, asset_id: UUID, tenant_id: UUID) -> FlowTemplateAsset:
        row = await self.session.execute(self._base_query().where(FlowTemplateAssets.id == asset_id).where(FlowTemplateAssets.tenant_id == tenant_id))
        item = row.mappings().one_or_none()
        if item is None:
            raise NotFoundException("Flow template asset not found.")
        return self._to_domain(item)

    async def list_for_flow(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowTemplateAsset]:
        rows = await self.session.execute(
            self._base_query()
            .where(FlowTemplateAssets.flow_id == flow_id)
            .where(FlowTemplateAssets.tenant_id == tenant_id)
            .order_by(FlowTemplateAssets.updated_at.desc(), FlowTemplateAssets.created_at.desc())
        )
        return [self._to_domain(item) for item in rows.mappings().all()]

    async def get_by_flow_file(
        self,
        *,
        flow_id: UUID,
        file_id: UUID,
        tenant_id: UUID,
    ) -> FlowTemplateAsset:
        row = await self.session.execute(
            self._base_query()
            .where(FlowTemplateAssets.flow_id == flow_id)
            .where(FlowTemplateAssets.file_id == file_id)
            .where(FlowTemplateAssets.tenant_id == tenant_id)
        )
        item = row.mappings().one_or_none()
        if item is None:
            raise NotFoundException("Flow template asset not found.")
        return self._to_domain(item)

    def _base_query(self):
        updated_by_name = sa.func.coalesce(Users.username, Users.email).label("last_updated_by_name")
        return (
            sa.select(FlowTemplateAssets, updated_by_name)
            .outerjoin(Users, Users.id == FlowTemplateAssets.updated_by_user_id)
            .where(FlowTemplateAssets.deleted_at.is_(None))
        )

    @staticmethod
    def _to_domain(row: sa.RowMapping) -> FlowTemplateAsset:
        asset = row[FlowTemplateAssets]
        return FlowTemplateAsset.model_validate(
            {
                "id": asset.id,
                "flow_id": asset.flow_id,
                "space_id": asset.space_id,
                "tenant_id": asset.tenant_id,
                "file_id": asset.file_id,
                "name": asset.name,
                "checksum": asset.checksum,
                "mimetype": asset.mimetype,
                "placeholders": list(asset.placeholders or []),
                "created_by_user_id": asset.created_by_user_id,
                "updated_by_user_id": asset.updated_by_user_id,
                "last_updated_by_name": row["last_updated_by_name"],
                "status": asset.status,
                "created_at": asset.created_at,
                "updated_at": asset.updated_at,
            }
        )
