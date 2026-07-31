from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.authentication.principal_types import PrincipalType
from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRunRerunOperations,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowVersions,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.files.file_models import FileContentVariant, FileType
from eneo.flows.enums import FlowRunRerunOperationStatus, FlowRunStatus
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    FlowRunHistoryPurgeCounts,
    FlowRunHistoryPurgeRepository,
    FlowRunHistoryPurgeResult,
)
from eneo.flows.principal import FlowPrincipal
from eneo.object_content.content import ContentState

_RUNTIME_UPLOAD_PAYLOAD = b"r" * 128


@dataclass(frozen=True, slots=True)
class _RuntimeUpload:
    file_id: UUID
    content_id: UUID
    flow_id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    principal: FlowPrincipal


@dataclass(frozen=True, slots=True)
class _BoundRuntimeUpload:
    upload: _RuntimeUpload
    run_id: UUID
    step_id: UUID


async def _create_runtime_upload(
    *,
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> _RuntimeUpload:
    async with db_container(user=admin_user) as container:
        session = container.session()
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
        session.add(flow)
        await session.flush()
        file = await container.file_service().save_generated_file(
            payload=_RUNTIME_UPLOAD_PAYLOAD,
            name=f"runtime-upload-lock-{uuid4()}.pdf",
            mimetype="application/pdf",
            file_type=FileType.DOCUMENT,
        )
        content_id = await session.scalar(
            sa.select(FileContentReferences.content_id).where(
                FileContentReferences.file_id == file.id
            )
        )
        assert content_id is not None

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
        return _RuntimeUpload(
            file_id=file.id,
            content_id=content_id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            owner_user_id=admin_user.id,
            principal=principal,
        )


async def _create_bound_runtime_upload(
    *,
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> _BoundRuntimeUpload:
    upload = await _create_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )
    run_id = uuid4()
    step_id = uuid4()
    now = datetime.now(timezone.utc)
    async with sessionmanager.session() as session, session.begin():
        flow = await session.get(Flows, upload.flow_id)
        assert flow is not None
        session.add(
            FlowVersions(
                flow_id=upload.flow_id,
                version=1,
                tenant_id=upload.tenant_id,
                definition_checksum=f"locking-{uuid4()}",
                definition_json={"schema_version": 1, "steps": []},
            )
        )
        await session.flush()
        flow.published_version = 1
        session.add(
            FlowRuns(
                id=run_id,
                flow_id=upload.flow_id,
                flow_version=1,
                principal_type="user",
                principal_user_id=upload.owner_user_id,
                principal_service_id=None,
                tenant_id=upload.tenant_id,
                trace_id=uuid4(),
                status=FlowRunStatus.COMPLETED.value,
                started_at=now,
                finished_at=now,
                input_payload_json={"input": "runtime source"},
                output_payload_json={"result": "complete"},
            )
        )
        await session.flush()
        session.add(
            FlowRunStepInputFiles(
                flow_run_id=run_id,
                flow_id=upload.flow_id,
                tenant_id=upload.tenant_id,
                step_id=step_id,
                step_order=1,
                attempt_no=1,
                file_id=upload.file_id,
                ordinal=0,
            )
        )
        await session.flush()
    return _BoundRuntimeUpload(upload=upload, run_id=run_id, step_id=step_id)


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


async def _purge_run(run_id: UUID) -> FlowRunHistoryPurgeResult:
    async with sessionmanager.session() as session, session.begin():
        return await FlowRunHistoryPurgeRepository(session).purge_run_history([run_id])


async def _sweep_abandoned_runtime_uploads(
    *, lock_timeout: str | None = None
) -> FlowRunHistoryPurgeCounts:
    async with sessionmanager.session() as session, session.begin():
        if lock_timeout is not None:
            if lock_timeout != "100ms":
                raise ValueError("Unsupported test lock timeout.")
            await session.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
        return await FlowRunHistoryPurgeRepository(
            session
        ).purge_abandoned_runtime_uploads(
            now=datetime.now(timezone.utc),
            limit=10,
        )


async def _make_runtime_upload_abandoned(upload: _RuntimeUpload) -> None:
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(FlowRuntimeUploadedFiles)
            .where(FlowRuntimeUploadedFiles.file_id == upload.file_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=2))
        )
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == upload.tenant_id)
            .values(
                flow_runtime_upload_abandonment_days=1,
                flow_run_history_minimum_retention_days=None,
                flow_run_history_no_purge=False,
            )
        )


async def _lock_runtime_upload_for_binding(
    *,
    upload: _RuntimeUpload,
    lock_timeout: str | None,
) -> set[UUID]:
    async with sessionmanager.session() as session, session.begin():
        if lock_timeout is not None:
            if lock_timeout != "100ms":
                raise ValueError("Unsupported test lock timeout.")
            await session.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
        return await FlowRuntimeUploadRepository(
            session=session
        ).list_bound_file_ids_for_owner(
            file_ids=[upload.file_id],
            flow_id=upload.flow_id,
            tenant_id=upload.tenant_id,
            principal=upload.principal,
            lock_for_binding=True,
        )


async def _add_retained_runtime_input(
    *,
    session: AsyncSession,
    fixture: _BoundRuntimeUpload,
) -> UUID:
    run_id = uuid4()
    now = datetime.now(timezone.utc)
    session.add(
        FlowRuns(
            id=run_id,
            flow_id=fixture.upload.flow_id,
            flow_version=1,
            principal_type="user",
            principal_user_id=fixture.upload.owner_user_id,
            principal_service_id=None,
            tenant_id=fixture.upload.tenant_id,
            trace_id=uuid4(),
            status=FlowRunStatus.RUNNING.value,
            started_at=now,
            finished_at=None,
            input_payload_json={"input": "retained source"},
            output_payload_json=None,
        )
    )
    await session.flush()
    session.add(
        FlowRunStepInputFiles(
            flow_run_id=run_id,
            flow_id=fixture.upload.flow_id,
            tenant_id=fixture.upload.tenant_id,
            step_id=fixture.step_id,
            step_order=1,
            attempt_no=1,
            file_id=fixture.upload.file_id,
            ordinal=0,
        )
    )
    await session.flush()
    return run_id


async def _runtime_source_rows_exist(
    *, fixture: _BoundRuntimeUpload
) -> tuple[bool, bool]:
    async with sessionmanager.session() as session, session.begin():
        file_exists = (
            await session.scalar(
                sa.select(Files.id).where(Files.id == fixture.upload.file_id)
            )
            is not None
        )
        upload_exists = (
            await session.scalar(
                sa.select(FlowRuntimeUploadedFiles.file_id).where(
                    FlowRuntimeUploadedFiles.file_id == fixture.upload.file_id
                )
            )
            is not None
        )
        return file_exists, upload_exists


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_upload_binding_lock_blocks_concurrent_delete(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    """`FOR KEY SHARE` keeps a runtime upload from being deleted while a run binds it."""
    upload = await _create_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )

    async with sessionmanager.session() as binding_session:
        async with binding_session.begin():
            repo = FlowRuntimeUploadRepository(session=binding_session)

            locked_ids = await repo.list_bound_file_ids_for_owner(
                file_ids=[upload.file_id],
                flow_id=upload.flow_id,
                tenant_id=upload.tenant_id,
                principal=upload.principal,
                lock_for_binding=True,
            )

            assert locked_ids == {upload.file_id}
            with pytest.raises(DBAPIError) as exc_info:
                await _delete_runtime_upload_with_lock_timeout(
                    file_id=upload.file_id,
                    flow_id=upload.flow_id,
                    tenant_id=upload.tenant_id,
                    lock_timeout="100ms",
                )
            assert getattr(exc_info.value.orig, "sqlstate", None) == "55P03"

    await _delete_runtime_upload_with_lock_timeout(
        file_id=upload.file_id,
        flow_id=upload.flow_id,
        tenant_id=upload.tenant_id,
        lock_timeout=None,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_upload_bind_first_keeps_source_during_run_purge(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    fixture = await _create_bound_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )

    async with sessionmanager.session() as binding_session:
        async with binding_session.begin():
            locked_ids = await FlowRuntimeUploadRepository(
                session=binding_session
            ).list_bound_file_ids_for_owner(
                file_ids=[fixture.upload.file_id],
                flow_id=fixture.upload.flow_id,
                tenant_id=fixture.upload.tenant_id,
                principal=fixture.upload.principal,
                lock_for_binding=True,
            )
            assert locked_ids == {fixture.upload.file_id}
            retained_run_id = await _add_retained_runtime_input(
                session=binding_session,
                fixture=fixture,
            )

            skipped_result = await _purge_run(fixture.run_id)
            assert skipped_result.counts.flow_runs_considered == 1
            assert skipped_result.counts.flow_runs_lock_deferred == 1
            assert skipped_result.counts.flow_runs_purged == 0

    purge_result = await _purge_run(fixture.run_id)

    assert purge_result.counts.flow_runs_purged == 1
    assert purge_result.counts.flow_runs_lock_deferred == 0
    assert purge_result.counts.flow_runtime_source_bindings_deleted == 0
    assert purge_result.counts.flow_runtime_source_files_deleted == 0
    assert await _runtime_source_rows_exist(fixture=fixture) == (True, True)
    async with sessionmanager.session() as session, session.begin():
        assert await session.get(FlowRuns, retained_run_id) is not None
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowRunStepInputFiles)
                .where(FlowRunStepInputFiles.flow_run_id == retained_run_id)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_upload_purge_first_blocks_binding_then_removes_source(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    fixture = await _create_bound_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )

    async with sessionmanager.session() as purge_session:
        async with purge_session.begin():
            purge_result = await FlowRunHistoryPurgeRepository(
                purge_session
            ).purge_run_history([fixture.run_id])
            assert purge_result.counts.flow_runtime_source_candidate_bytes == len(
                _RUNTIME_UPLOAD_PAYLOAD
            )
            assert purge_result.counts.flow_runtime_source_files_deleted == 1
            assert purge_result.counts.flow_runtime_source_bytes_deleted == len(
                _RUNTIME_UPLOAD_PAYLOAD
            )

            with pytest.raises(DBAPIError) as exc_info:
                await _lock_runtime_upload_for_binding(
                    upload=fixture.upload,
                    lock_timeout="100ms",
                )
            assert getattr(exc_info.value.orig, "sqlstate", None) == "55P03"

    assert (
        await _lock_runtime_upload_for_binding(
            upload=fixture.upload,
            lock_timeout=None,
        )
        == set()
    )
    assert await _runtime_source_rows_exist(fixture=fixture) == (False, False)
    async with sessionmanager.session() as session, session.begin():
        content = await session.get(ObjectContents, fixture.upload.content_id)
        assert content is not None
        assert content.state == ContentState.DELETE_PENDING.value
        assert content.reference_count == 0
        assert content.delete_requested_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_runtime_upload_bind_during_abandonment_sweep_survives(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    fixture = await _create_bound_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )
    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.delete(FlowRunStepInputFiles).where(
                FlowRunStepInputFiles.flow_run_id == fixture.run_id
            )
        )
    await _make_runtime_upload_abandoned(fixture.upload)

    async with sessionmanager.session() as binding_session:
        async with binding_session.begin():
            locked_ids = await FlowRuntimeUploadRepository(
                session=binding_session
            ).list_bound_file_ids_for_owner(
                file_ids=[fixture.upload.file_id],
                flow_id=fixture.upload.flow_id,
                tenant_id=fixture.upload.tenant_id,
                principal=fixture.upload.principal,
                lock_for_binding=True,
            )
            assert locked_ids == {fixture.upload.file_id}
            retained_run_id = await _add_retained_runtime_input(
                session=binding_session,
                fixture=fixture,
            )

            skipped_counts = await _sweep_abandoned_runtime_uploads()
            assert skipped_counts.flow_runtime_source_candidates == 0
            assert skipped_counts.flow_runtime_source_bindings_deleted == 0
            assert skipped_counts.flow_runtime_source_files_deleted == 0

    repeated_counts = await _sweep_abandoned_runtime_uploads()

    assert repeated_counts.flow_runtime_source_candidates == 0
    assert repeated_counts.flow_runtime_source_bindings_deleted == 0
    assert repeated_counts.flow_runtime_source_files_deleted == 0
    assert await _runtime_source_rows_exist(fixture=fixture) == (True, True)
    async with sessionmanager.session() as session, session.begin():
        assert await session.get(FlowRuns, retained_run_id) is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_abandonment_sweep_skips_file_locked_for_deletion(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    upload = await _create_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )
    await _make_runtime_upload_abandoned(upload)

    async with sessionmanager.session() as deletion_session:
        async with deletion_session.begin():
            locked_file_id = await deletion_session.scalar(
                sa.select(Files.id)
                .where(Files.id == upload.file_id)
                .with_for_update(of=Files)
            )
            assert locked_file_id == upload.file_id

            skipped_counts = await _sweep_abandoned_runtime_uploads(
                lock_timeout="100ms"
            )
            assert skipped_counts.flow_runtime_source_candidates == 0
            assert skipped_counts.flow_runtime_source_bindings_deleted == 0
            assert skipped_counts.flow_runtime_source_files_deleted == 0

            await deletion_session.execute(
                sa.delete(Files).where(Files.id == upload.file_id)
            )

    async with sessionmanager.session() as session, session.begin():
        assert await session.get(Files, upload.file_id) is None
        assert await session.get(FlowRuntimeUploadedFiles, upload.file_id) is None
        content = await session.get(ObjectContents, upload.content_id)
        assert content is not None
        assert content.state == ContentState.DELETE_PENDING.value
        assert content.reference_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_abandonment_sweep_reports_file_bytes_while_shared_content_remains(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    upload = await _create_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )
    await _make_runtime_upload_abandoned(upload)
    retained_file_id = uuid4()
    async with sessionmanager.session() as session, session.begin():
        session.add(
            Files(
                id=retained_file_id,
                name="retained-shared-runtime-content.pdf",
                mimetype="application/pdf",
                file_type=FileType.DOCUMENT.value,
                owner_type="user",
                owner_user_id=upload.owner_user_id,
                owner_service_id=None,
                tenant_id=upload.tenant_id,
                parent_file_id=None,
            )
        )
        await session.flush()
        session.add(
            FileContentReferences(
                file_id=retained_file_id,
                content_id=upload.content_id,
                variant=FileContentVariant.ORIGINAL.value,
                ordinal=0,
            )
        )

    counts = await _sweep_abandoned_runtime_uploads()

    assert counts.flow_runtime_source_candidates == 1
    assert counts.flow_runtime_source_candidate_bytes == len(_RUNTIME_UPLOAD_PAYLOAD)
    assert counts.flow_runtime_source_bindings_deleted == 1
    assert counts.flow_runtime_source_files_deleted == 1
    assert counts.flow_runtime_source_bytes_deleted == len(_RUNTIME_UPLOAD_PAYLOAD)
    async with sessionmanager.session() as session, session.begin():
        assert await session.get(Files, upload.file_id) is None
        assert await session.get(Files, retained_file_id) is not None
        content = await session.get(ObjectContents, upload.content_id)
        assert content is not None
        assert content.state == ContentState.AVAILABLE.value
        assert content.reference_count == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_run_purge_skips_rerun_that_wins_the_run_lock(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    fixture = await _create_bound_runtime_upload(
        db_container=db_container,
        completion_model_factory=completion_model_factory,
        space_factory=space_factory,
        admin_user=admin_user,
    )

    async with sessionmanager.session() as rerun_session:
        async with rerun_session.begin():
            locked_run_id = await rerun_session.scalar(
                sa.select(FlowRuns.id)
                .where(FlowRuns.id == fixture.run_id)
                .with_for_update()
            )
            assert locked_run_id == fixture.run_id
            rerun_session.add(
                FlowRunRerunOperations(
                    tenant_id=fixture.upload.tenant_id,
                    flow_id=fixture.upload.flow_id,
                    flow_run_id=fixture.run_id,
                    rerun_step_id=fixture.step_id,
                    rerun_step_order=1,
                    root_attempt_no=2,
                    root_attempt_id=None,
                    status=FlowRunRerunOperationStatus.QUEUED.value,
                    request_fingerprint=f"rerun-lock-{uuid4()}",
                    expected_run_revision=1,
                    accepted_run_revision=1,
                    reason="Rerun wins the run lock.",
                    input_payload_json=None,
                    root_step_input_override_requested=False,
                    requested_by_principal_type="user",
                    requested_by_user_id=fixture.upload.owner_user_id,
                    requested_by_service_id=None,
                )
            )
            await rerun_session.execute(
                sa.update(FlowRuns)
                .where(FlowRuns.id == fixture.run_id)
                .values(
                    status=FlowRunStatus.QUEUED.value,
                    finished_at=None,
                )
            )
            await rerun_session.flush()

            skipped_result = await _purge_run(fixture.run_id)
            assert skipped_result.counts.flow_runs_considered == 1
            assert skipped_result.counts.flow_runs_lock_deferred == 1
            assert skipped_result.counts.flow_runs_purged == 0

    assert await _runtime_source_rows_exist(fixture=fixture) == (True, True)
    async with sessionmanager.session() as session, session.begin():
        run = await session.get(FlowRuns, fixture.run_id)
        assert run is not None
        assert run.status == FlowRunStatus.QUEUED.value
