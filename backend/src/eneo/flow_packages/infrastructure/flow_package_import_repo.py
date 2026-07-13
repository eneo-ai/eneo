from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowPackageImports, Flows
from eneo.database.tables.spaces_table import Spaces
from eneo.flow_packages.domain.flow_package_import_plan import (
    FlowPackageImportPlan,
    FlowPackageImportTargetState,
)
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportFailurePayload,
    FlowPackageImportSelection,
    FlowPackageImportSource,
    FlowPackageImportStatus,
)
from eneo.json_types import JsonObject


class FlowPackageImportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_space_import_lock(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
    ) -> None:
        locked_space = await self._session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id)
            .where(Spaces.tenant_id == tenant_id)
            .with_for_update()
        )
        if locked_space is not None:
            space_row = await self._session.get(Spaces, locked_space)
            if space_row is not None:
                space_mapper = sa.inspect(Spaces)
                if space_mapper is None:
                    raise RuntimeError("Spaces ORM mapper is unavailable.")
                self._session.expire(
                    space_row,
                    attribute_names=list(space_mapper.relationships.keys()),
                )

    async def get_successful_retry(
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        content_checksum: str,
        target_state: FlowPackageImportTargetState,
        selection: FlowPackageImportSelection,
    ) -> "SuccessfulFlowPackageImport | None":
        row = (
            await self._session.execute(
                sa.select(
                    FlowPackageImports.id,
                    FlowPackageImports.flow_id,
                    Flows.name,
                )
                .join(
                    Flows,
                    sa.and_(
                        FlowPackageImports.flow_id == Flows.id,
                        FlowPackageImports.tenant_id == Flows.tenant_id,
                        FlowPackageImports.space_id == Flows.space_id,
                    ),
                )
                .where(Flows.deleted_at.is_(None))
                .where(FlowPackageImports.tenant_id == tenant_id)
                .where(FlowPackageImports.space_id == space_id)
                .where(FlowPackageImports.content_checksum == content_checksum)
                .where(
                    FlowPackageImports.status
                    == FlowPackageImportStatus.DRAFT_CREATED.value
                )
                .where(
                    FlowPackageImports.selected_mappings_json
                    == _selection_json(selection)
                )
                .where(
                    FlowPackageImports.import_plan_json["target_state"]
                    == _model_json(target_state)
                )
                .order_by(FlowPackageImports.created_at)
                .limit(1)
            )
        ).one_or_none()
        if row is None:
            return None
        import_id, flow_id, flow_name = row
        if flow_id is None:
            raise RuntimeError("Successful Flow package import has no Flow.")
        return SuccessfulFlowPackageImport(
            import_id=import_id,
            flow_id=flow_id,
            flow_name=flow_name,
        )

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
            "selected_mappings_json": _selection_json(selection),
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
    return cast(JsonObject, import_plan.storage_json())


def _model_json(model: BaseModel) -> JsonObject:
    return cast(JsonObject, model.model_dump(mode="json"))


def _selection_json(selection: FlowPackageImportSelection) -> JsonObject:
    return cast(JsonObject, selection.storage_json())


@dataclass(frozen=True, slots=True)
class SuccessfulFlowPackageImport:
    import_id: UUID
    flow_id: UUID
    flow_name: str
