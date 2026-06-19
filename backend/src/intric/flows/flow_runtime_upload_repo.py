from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession
from intric.database.tables.flow_tables import FlowRuntimeUploadedFiles
from intric.flows.principal import FlowPrincipal


class FlowRuntimeUploadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        file_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        uploaded_for_step_id: UUID,
        principal: FlowPrincipal,
    ) -> None:
        await self.session.execute(
            sa.insert(FlowRuntimeUploadedFiles).values(
                file_id=file_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                uploaded_for_step_id=uploaded_for_step_id,
                owner_type=principal.principal_type.value,
                owner_user_id=principal.principal_user_id,
                owner_service_id=principal.principal_service_id,
            )
        )

    async def exists_for_owner(
        self,
        *,
        file_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        principal: FlowPrincipal,
    ) -> bool:
        stmt = (
            sa.select(FlowRuntimeUploadedFiles.file_id)
            .where(FlowRuntimeUploadedFiles.file_id == file_id)
            .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
            .where(FlowRuntimeUploadedFiles.tenant_id == tenant_id)
            .where(
                FlowRuntimeUploadedFiles.owner_type == principal.principal_type.value
            )
        )
        if principal.principal_user_id is not None:
            stmt = stmt.where(
                FlowRuntimeUploadedFiles.owner_user_id == principal.principal_user_id
            )
        if principal.principal_service_id is not None:
            stmt = stmt.where(
                FlowRuntimeUploadedFiles.owner_service_id
                == principal.principal_service_id
            )
        return await self.session.scalar(stmt.limit(1)) is not None

    async def list_bound_file_ids_for_owner(
        self,
        *,
        file_ids: list[UUID],
        flow_id: UUID,
        tenant_id: UUID,
        principal: FlowPrincipal,
        lock_for_binding: bool = False,
    ) -> set[UUID]:
        if not file_ids:
            return set()

        stmt = (
            sa.select(FlowRuntimeUploadedFiles.file_id)
            .where(FlowRuntimeUploadedFiles.file_id.in_(file_ids))
            .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
            .where(FlowRuntimeUploadedFiles.tenant_id == tenant_id)
            .where(
                FlowRuntimeUploadedFiles.owner_type == principal.principal_type.value
            )
        )
        if principal.principal_user_id is not None:
            stmt = stmt.where(
                FlowRuntimeUploadedFiles.owner_user_id == principal.principal_user_id
            )
        if principal.principal_service_id is not None:
            stmt = stmt.where(
                FlowRuntimeUploadedFiles.owner_service_id
                == principal.principal_service_id
            )
        if lock_for_binding:
            if not self.session.in_transaction():
                raise RuntimeError(
                    "Runtime upload binding locks require an active transaction."
                )
            stmt = stmt.with_for_update(
                read=True,
                key_share=True,
                of=FlowRuntimeUploadedFiles,
            )

        return set(await self.session.scalars(stmt))
