from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import FlowPackageImports
from intric.flow_packages.domain.flow_package_import_plan import FlowPackageImportPlan
from intric.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportFailurePayload,
    FlowPackageImportSelection,
    FlowPackageImportSource,
    FlowPackageImportStatus,
)
from intric.flow_packages.domain.flow_package_manifest import JsonObject


class FlowPackageImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_draft_created(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        flow_id: UUID,
        created_by_user_id: UUID | None,
        package_id: str,
        package_version: str,
        content_checksum: str,
        import_plan: FlowPackageImportPlan,
        selection: FlowPackageImportSelection,
    ) -> UUID:
        return await self._insert_import_record(
            tenant_id=tenant_id,
            space_id=space_id,
            flow_id=flow_id,
            created_by_user_id=created_by_user_id,
            package_id=package_id,
            package_version=package_version,
            content_checksum=content_checksum,
            status=FlowPackageImportStatus.DRAFT_CREATED,
            import_plan=import_plan,
            selection=selection,
            failure=None,
        )

    async def create_failed(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        created_by_user_id: UUID | None,
        package_id: str,
        package_version: str,
        content_checksum: str,
        import_plan: FlowPackageImportPlan,
        selection: FlowPackageImportSelection,
        failure: FlowPackageImportFailurePayload,
    ) -> UUID:
        return await self._insert_import_record(
            tenant_id=tenant_id,
            space_id=space_id,
            flow_id=None,
            created_by_user_id=created_by_user_id,
            package_id=package_id,
            package_version=package_version,
            content_checksum=content_checksum,
            status=FlowPackageImportStatus.FAILED,
            import_plan=import_plan,
            selection=selection,
            failure=failure,
        )

    async def _insert_import_record(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        flow_id: UUID | None,
        created_by_user_id: UUID | None,
        package_id: str,
        package_version: str,
        content_checksum: str,
        status: FlowPackageImportStatus,
        import_plan: FlowPackageImportPlan,
        selection: FlowPackageImportSelection,
        failure: FlowPackageImportFailurePayload | None,
    ) -> UUID:
        values: dict[str, object] = {
            "tenant_id": tenant_id,
            "space_id": space_id,
            "flow_id": flow_id,
            "created_by_user_id": created_by_user_id,
            "package_id": package_id,
            "package_version": package_version,
            "content_checksum": content_checksum,
            "source": FlowPackageImportSource.FILE_UPLOAD.value,
            "status": status.value,
            "import_plan_json": _import_plan_json(import_plan),
            "selected_mappings_json": _model_json(selection),
        }
        if failure is not None:
            values["failure_json"] = _model_json(failure)

        import_id = await self._session.scalar(
            sa.insert(FlowPackageImports)
            .values(values)
            .returning(FlowPackageImports.id)
        )
        if import_id is None:
            raise RuntimeError("Flow package import record was not created.")
        return import_id


def _import_plan_json(import_plan: FlowPackageImportPlan) -> JsonObject:
    # Exclude can_publish_after_import: API read models recompute this flag.
    return cast(
        JsonObject,
        import_plan.model_dump(
            mode="json",
            exclude={"can_publish_after_import"},
        ),
    )


def _model_json(model: BaseModel) -> JsonObject:
    return cast(JsonObject, model.model_dump(mode="json"))
