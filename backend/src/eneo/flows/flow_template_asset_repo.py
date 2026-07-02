from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.flow_tables import FlowTemplateAssets
from eneo.database.tables.users_table import Users
from eneo.flows.domain.flow import FlowTemplateAsset
from eneo.main.exceptions import NotFoundException


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
        return await self.get(asset_id=row.id, tenant_id=tenant_id)

    async def get(self, *, asset_id: UUID, tenant_id: UUID) -> FlowTemplateAsset:
        row = await self.session.execute(
            self._base_query()
            .where(FlowTemplateAssets.id == asset_id)
            .where(FlowTemplateAssets.tenant_id == tenant_id)
        )
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
            .order_by(
                FlowTemplateAssets.updated_at.desc(),
                FlowTemplateAssets.created_at.desc(),
            )
        )
        return [self._to_domain(item) for item in rows.mappings().all()]

    async def soft_delete(
        self,
        *,
        asset_id: UUID,
        tenant_id: UUID,
        updated_by_user_id: UUID | None,
    ) -> None:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            sa.update(FlowTemplateAssets)
            .where(FlowTemplateAssets.id == asset_id)
            .where(FlowTemplateAssets.tenant_id == tenant_id)
            .where(FlowTemplateAssets.deleted_at.is_(None))
            .values(
                deleted_at=now,
                updated_at=now,
                updated_by_user_id=updated_by_user_id,
            )
        )
        if _affected_row_count(result) == 0:
            raise NotFoundException("Flow template asset not found.")

    def _base_query(self):
        updated_by_name = sa.func.coalesce(Users.username, Users.email).label(
            "last_updated_by_name"
        )
        return (
            sa.select(FlowTemplateAssets, updated_by_name)
            .outerjoin(Users, Users.id == FlowTemplateAssets.updated_by_user_id)
            .where(FlowTemplateAssets.deleted_at.is_(None))
        )

    @staticmethod
    def _to_domain(row: sa.RowMapping) -> FlowTemplateAsset:
        row_dict = dict(row)
        asset = next(
            (
                value
                for value in row_dict.values()
                if isinstance(value, FlowTemplateAssets)
            ),
            None,
        )
        if asset is None:
            raise NotFoundException("Flow template asset row was malformed.")
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
                "last_updated_by_name": row_dict.get("last_updated_by_name"),
                "status": asset.status,
                "created_at": asset.created_at,
                "updated_at": asset.updated_at,
            }
        )


def _affected_row_count(result: object) -> int:
    rowcount = getattr(result, "rowcount", 0)
    return rowcount if isinstance(rowcount, int) else 0
