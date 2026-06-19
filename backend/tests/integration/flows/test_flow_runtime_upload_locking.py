from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from intric.authentication.principal_types import PrincipalType
from intric.database.database import sessionmanager
from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import FlowRuntimeUploadedFiles, Flows
from intric.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from intric.flows.principal import FlowPrincipal


async def _create_runtime_upload(
    *,
    completion_model_factory,
    space_factory,
    admin_user,
) -> tuple[UUID, UUID, UUID, FlowPrincipal]:
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(
            session,
            f"runtime-upload-lock-model-{uuid4()}",
        )
        space = await space_factory(
            session,
            f"Runtime upload lock space {uuid4()}",
            [model.id],
        )
        flow = Flows(
            name=f"Runtime upload lock flow {uuid4()}",
            description=None,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json=None,
            data_retention_days=30,
        )
        file = Files(
            name=f"runtime-upload-lock-{uuid4()}.pdf",
            text="runtime file",
            blob=None,
            checksum=f"runtime-upload-lock-{uuid4()}",
            size=128,
            mimetype="application/pdf",
            file_type="document",
            transcription=None,
            owner_type="user",
            owner_user_id=admin_user.id,
            owner_service_id=None,
            tenant_id=admin_user.tenant_id,
        )
        session.add_all([flow, file])
        await session.flush()

        upload = FlowRuntimeUploadedFiles(
            file_id=file.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            uploaded_for_step_id=uuid4(),
            owner_type="user",
            owner_user_id=admin_user.id,
            owner_service_id=None,
        )
        session.add(upload)
        await session.flush()

        principal = FlowPrincipal(
            principal_type=PrincipalType.USER,
            principal_user_id=admin_user.id,
        )
        return file.id, flow.id, admin_user.tenant_id, principal


async def _delete_runtime_upload_with_lock_timeout(
    *,
    file_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    lock_timeout: str | None,
) -> None:
    async with sessionmanager.session() as session:
        async with session.begin():
            if lock_timeout is not None:
                if lock_timeout != "100ms":
                    raise ValueError("Unsupported test lock timeout.")
                await session.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            await session.execute(
                sa.delete(FlowRuntimeUploadedFiles)
                .where(FlowRuntimeUploadedFiles.file_id == file_id)
                .where(FlowRuntimeUploadedFiles.flow_id == flow_id)
                .where(FlowRuntimeUploadedFiles.tenant_id == tenant_id)
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_upload_binding_lock_blocks_concurrent_delete(
    setup_database,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    """`FOR KEY SHARE` keeps a runtime upload from being deleted while a run binds it."""
    file_id, flow_id, tenant_id, principal = await _create_runtime_upload(
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )

    async with sessionmanager.session() as binding_session:
        async with binding_session.begin():
            repo = FlowRuntimeUploadRepository(session=binding_session)

            locked_ids = await repo.list_bound_file_ids_for_owner(
                file_ids=[file_id],
                flow_id=flow_id,
                tenant_id=tenant_id,
                principal=principal,
                lock_for_binding=True,
            )

            assert locked_ids == {file_id}
            with pytest.raises(DBAPIError) as exc_info:
                await _delete_runtime_upload_with_lock_timeout(
                    file_id=file_id,
                    flow_id=flow_id,
                    tenant_id=tenant_id,
                    lock_timeout="100ms",
                )
            assert getattr(exc_info.value.orig, "sqlstate", None) == "55P03"

    await _delete_runtime_upload_with_lock_timeout(
        file_id=file_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        lock_timeout=None,
    )
