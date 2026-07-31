from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.job_table import Jobs
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob import InfoBlobInDB
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import (
    KnowledgeOriginalAdmission,
    Transcription,
    UploadInfoBlob,
)
from eneo.main.container.container import Container, SessionProxy
from eneo.main.models import ChannelType, RedisMessage, Status
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import StorageKind
from eneo.object_content.content_service import ObjectContentService
from eneo.worker import routes as worker_routes
from eneo.worker import task_manager as task_manager_module
from eneo.worker import upload_tasks
from eneo.worker.task_manager import TaskManager
from eneo.worker.upload_tasks import transcription_task, upload_info_blob_task

pytestmark = pytest.mark.integration


class StubExtractor:
    def extract(
        self, filepath: Path, mimetype: str, filename: str | None = None
    ) -> str:
        return "replacement knowledge"


def _original_admission() -> KnowledgeOriginalAdmission:
    return KnowledgeOriginalAdmission(
        policy_revision=1,
        storage_target=StorageKind.POSTGRES_INLINE,
        maximum_bytes=1_000_000,
    )


def _worker_container(*, user, tenant) -> Container:
    container = Container(
        session=providers.Object(SessionProxy()),
        user=providers.Object(user),
        tenant=providers.Object(tenant),
    )
    container.object_content_service.override(
        providers.Object(
            ObjectContentService(
                ObjectContentCoreSettings(_env_file=None),
                sessionmanager,
            )
        )
    )
    return container


async def _job_updated_at(job_id: UUID) -> datetime:
    async with sessionmanager.session() as session, session.begin():
        updated_at = await session.scalar(
            sa.select(Jobs.updated_at).where(Jobs.id == job_id)
        )
    assert updated_at is not None
    return updated_at


async def test_concurrent_deliveries_start_compute_at_most_once_and_preserve_staging(
    db_container, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        tenant = setup.tenant()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.QUEUED.value,
            )
        )

    filepath = job_staging_path(job_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"replacement")

    compute_started = asyncio.Event()
    allow_compute_to_finish = asyncio.Event()
    compute_entries = 0

    async def process_text(**_kwargs: object) -> SimpleNamespace:
        nonlocal compute_entries
        compute_entries += 1
        compute_started.set()
        await allow_compute_to_finish.wait()
        return SimpleNamespace(id=uuid4())

    async def deliver() -> bool | None:
        container = _worker_container(user=user, tenant=tenant)
        container.text_extractor.override(providers.Object(StubExtractor()))
        container.group_service.override(
            providers.Object(
                SimpleNamespace(
                    get_group=AsyncMock(
                        return_value=SimpleNamespace(embedding_model=object())
                    )
                )
            )
        )
        container.text_processor.override(
            providers.Object(SimpleNamespace(process_text=process_text))
        )
        return await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=uuid4(),
                space_id=uuid4(),
                filename="replacement.txt",
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=container,
        )

    deliveries = [asyncio.create_task(deliver()) for _ in range(2)]
    try:
        await asyncio.wait_for(compute_started.wait(), timeout=5)
        for _ in range(100):
            if any(delivery.done() for delivery in deliveries):
                break
            await asyncio.sleep(0.01)

        assert compute_entries == 1
        assert any(delivery.done() for delivery in deliveries)
        assert filepath.exists()
    finally:
        allow_compute_to_finish.set()
        await asyncio.gather(*deliveries)


async def test_successful_upload_publishes_cas_statuses_without_generic_db_writes(
    db_container, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        tenant = setup.tenant()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.QUEUED.value,
            )
        )

    filepath = job_staging_path(job_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"replacement")
    redis_publish = AsyncMock()
    monkeypatch.setattr(
        task_manager_module,
        "r",
        SimpleNamespace(publish=redis_publish),
    )

    container = _worker_container(user=user, tenant=tenant)
    job_service = container.job_service()
    set_status = AsyncMock()
    complete_job = AsyncMock()
    monkeypatch.setattr(job_service, "set_status", set_status)
    monkeypatch.setattr(job_service, "complete_job", complete_job)
    container.task_manager.override(
        providers.Factory(
            TaskManager,
            user=user,
            job_service=job_service,
            channel_type=ChannelType.APP_RUN_UPDATES,
        )
    )
    container.text_extractor.override(providers.Object(StubExtractor()))
    container.group_service.override(
        providers.Object(
            SimpleNamespace(
                get_group=AsyncMock(
                    return_value=SimpleNamespace(embedding_model=object())
                )
            )
        )
    )
    container.text_processor.override(
        providers.Object(
            SimpleNamespace(
                process_text=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            )
        )
    )

    result = await upload_info_blob_task(
        job_id=job_id,
        params=UploadInfoBlob(
            user_id=user.id,
            group_id=uuid4(),
            space_id=uuid4(),
            filename="replacement.txt",
            mimetype="text/plain",
            original_storage=_original_admission(),
        ),
        container=container,
    )

    published_statuses = [
        RedisMessage.model_validate_json(call.args[1]).status
        for call in redis_publish.await_args_list
    ]
    assert result is True
    assert published_statuses == [Status.IN_PROGRESS, Status.COMPLETE]
    set_status.assert_not_awaited()
    complete_job.assert_not_awaited()


async def test_transcription_releases_its_session_before_remote_work(
    db_container, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        tenant = setup.tenant()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.TRANSCRIPTION.value,
                status=Status.QUEUED.value,
            )
        )

    filepath = job_staging_path(job_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"audio")
    container = _worker_container(user=user, tenant=tenant)

    class ScopeObservingTranscriber:
        session_released = False

        async def prepare_transcription(self, _model: object) -> object:
            return object()

        async def _remote_transcription(self) -> str:
            try:
                await container.session().execute(sa.select(1))
            except RuntimeError:
                self.session_released = True
            async with sessionmanager.session() as session, session.begin():
                assert await session.scalar(sa.select(1)) == 1
            return "replacement transcript"

        async def transcribe_from_filepath(self, **_kwargs: object) -> str:
            return await self._remote_transcription()

        async def transcribe_prepared_from_filepath(self, **_kwargs: object) -> str:
            return await self._remote_transcription()

    transcriber = ScopeObservingTranscriber()
    container.transcriber.override(providers.Object(transcriber))
    container.space_service.override(
        providers.Object(
            SimpleNamespace(
                get_space=AsyncMock(
                    return_value=SimpleNamespace(
                        get_default_transcription_model=lambda: object()
                    )
                )
            )
        )
    )
    container.group_service.override(
        providers.Object(
            SimpleNamespace(
                get_group=AsyncMock(
                    return_value=SimpleNamespace(embedding_model=object())
                )
            )
        )
    )
    container.text_processor.override(
        providers.Object(
            SimpleNamespace(
                process_text=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
            )
        )
    )

    result = await transcription_task(
        job_id=job_id,
        params=Transcription(
            user_id=user.id,
            group_id=uuid4(),
            space_id=uuid4(),
            filename="replacement.wav",
            mimetype="audio/wav",
            original_storage=_original_admission(),
        ),
        container=container,
    )

    assert result is True
    assert transcriber.session_released is True


@pytest.mark.parametrize("stalled_phase", ["extraction", "chunking", "embedding"])
async def test_heartbeat_advances_updated_at_during_each_compute_phase(
    db_container, tmp_path, monkeypatch, stalled_phase: str
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    monkeypatch.setattr(
        upload_tasks,
        "KNOWLEDGE_HEARTBEAT_INTERVAL_SECONDS",
        0.05,
        raising=False,
    )
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        tenant = setup.tenant()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.QUEUED.value,
            )
        )

    filepath = job_staging_path(job_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"replacement")

    phase_started_at: datetime | None = None
    phase_finished = asyncio.Event()
    allow_task_to_finish = asyncio.Event()
    allow_embedding_to_finish = asyncio.Event()

    def stall_sync_phase() -> None:
        nonlocal phase_started_at
        phase_started_at = datetime.now(timezone.utc)
        release = threading.Event()
        threading.Timer(0.25, release.set).start()
        assert release.wait(timeout=2)

    class PhaseExtractor:
        def extract(
            self, filepath: Path, mimetype: str, filename: str | None = None
        ) -> str:
            if stalled_phase == "extraction":
                stall_sync_phase()
            return "replacement knowledge"

    original_chunk_text = Datastore._chunk_text

    def chunk_text(datastore: Datastore, info_blob: InfoBlobInDB):
        if stalled_phase == "chunking":
            stall_sync_phase()
        return original_chunk_text(datastore, info_blob)

    monkeypatch.setattr(Datastore, "_chunk_text", chunk_text)

    class Embeddings:
        async def get_embeddings(self, *, model, chunks):
            nonlocal phase_started_at
            if stalled_phase == "embedding":
                phase_started_at = datetime.now(timezone.utc)
                phase_finished.set()
                await allow_embedding_to_finish.wait()
            result = ChunkEmbeddingList()
            result.add(chunks, [[0.1, 0.2, 0.3] for _ in chunks])
            return result

    chunk_repo = SimpleNamespace(add=AsyncMock())
    datastore = Datastore(
        user=user,
        info_blob_chunk_repo=chunk_repo,
        create_embeddings_service=Embeddings(),
    )

    async def process_text(**_kwargs: object) -> SimpleNamespace:
        await datastore.add(
            InfoBlobInDB(
                id=uuid4(),
                embedding_model_id=uuid4(),
                user_id=user.id,
                tenant_id=user.tenant_id,
                size=0,
                source_id=uuid4(),
                version_state="active",
                text="replacement knowledge",
                group_id=uuid4(),
            ),
            embedding_model=object(),
        )
        phase_finished.set()
        await allow_task_to_finish.wait()
        return SimpleNamespace(id=uuid4())

    container = _worker_container(user=user, tenant=tenant)
    container.text_extractor.override(providers.Object(PhaseExtractor()))
    container.group_service.override(
        providers.Object(
            SimpleNamespace(
                get_group=AsyncMock(
                    return_value=SimpleNamespace(embedding_model=object())
                )
            )
        )
    )
    container.text_processor.override(
        providers.Object(SimpleNamespace(process_text=process_text))
    )

    task = asyncio.create_task(
        upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=uuid4(),
                space_id=uuid4(),
                filename="replacement.txt",
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=container,
        )
    )
    try:
        await asyncio.wait_for(phase_finished.wait(), timeout=5)
        assert phase_started_at is not None
        if stalled_phase == "embedding":
            await asyncio.sleep(0.15)
        assert await _job_updated_at(job_id) > phase_started_at
    finally:
        allow_embedding_to_finish.set()
        allow_task_to_finish.set()
        await task


async def test_heartbeat_recovers_after_one_failed_database_update(
    db_container, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    monkeypatch.setattr(
        upload_tasks,
        "KNOWLEDGE_HEARTBEAT_INTERVAL_SECONDS",
        0.05,
        raising=False,
    )
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        tenant = setup.tenant()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.QUEUED.value,
            )
        )

    filepath = job_staging_path(job_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"replacement")
    phase_started_at = datetime.now(timezone.utc)
    allow_task_to_finish = asyncio.Event()
    original_touch_job = JobRepository.touch_job
    beat_attempts = 0

    async def fail_first_beat(self: JobRepository, touched_job_id: UUID) -> bool:
        nonlocal beat_attempts
        beat_attempts += 1
        if beat_attempts == 1:
            raise RuntimeError("transient heartbeat failure")
        return await original_touch_job(self, touched_job_id)

    monkeypatch.setattr(JobRepository, "touch_job", fail_first_beat)

    async def process_text(**_kwargs: object) -> SimpleNamespace:
        await allow_task_to_finish.wait()
        return SimpleNamespace(id=uuid4())

    container = _worker_container(user=user, tenant=tenant)
    container.text_extractor.override(providers.Object(StubExtractor()))
    container.group_service.override(
        providers.Object(
            SimpleNamespace(
                get_group=AsyncMock(
                    return_value=SimpleNamespace(embedding_model=object())
                )
            )
        )
    )
    container.text_processor.override(
        providers.Object(SimpleNamespace(process_text=process_text))
    )

    task = asyncio.create_task(
        upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=uuid4(),
                space_id=uuid4(),
                filename="replacement.txt",
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=container,
        )
    )
    try:
        for _ in range(100):
            await asyncio.sleep(0.02)
            if beat_attempts >= 2 and await _job_updated_at(job_id) > phase_started_at:
                break
        assert beat_attempts >= 2
        assert await _job_updated_at(job_id) > phase_started_at
    finally:
        allow_task_to_finish.set()
        await task


async def test_heartbeat_does_not_touch_failed_job(db_container, monkeypatch) -> None:
    monkeypatch.setattr(
        upload_tasks,
        "KNOWLEDGE_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
        raising=False,
    )
    job_id = uuid4()
    failed_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with db_container() as setup:
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=setup.user().id,
                task=Task.UPLOAD_FILE.value,
                status=Status.FAILED.value,
                updated_at=failed_at,
            )
        )

    owner_task = asyncio.create_task(asyncio.Event().wait())
    heartbeat = asyncio.create_task(
        upload_tasks._run_knowledge_heartbeat(
            Container(session=providers.Object(SessionProxy())),
            job_id,
            owner_task,
        )
    )
    await asyncio.wait_for(heartbeat, timeout=1)
    with pytest.raises(asyncio.CancelledError):
        await owner_task

    assert await _job_updated_at(job_id) == failed_at


@pytest.mark.parametrize("reaped_before_cancel", [False, True])
async def test_cancelled_upload_uses_guarded_failure_and_reraises(
    db_container,
    tmp_path,
    monkeypatch,
    reaped_before_cancel: bool,
) -> None:
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    monkeypatch.setattr(
        upload_tasks,
        "KNOWLEDGE_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        tenant = setup.tenant()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.QUEUED.value,
            )
        )

    filepath = job_staging_path(job_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(b"replacement")
    redis_publish = AsyncMock()
    failure_log = MagicMock()
    monkeypatch.setattr(
        task_manager_module,
        "r",
        SimpleNamespace(publish=redis_publish),
    )
    monkeypatch.setattr(
        upload_tasks,
        "logger",
        SimpleNamespace(warning=failure_log),
    )
    compute_started = asyncio.Event()
    compute_cancelled = asyncio.Event()

    async def process_text(**_kwargs: object) -> SimpleNamespace:
        compute_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            compute_cancelled.set()
            raise
        raise AssertionError("unreachable")

    container = _worker_container(user=user, tenant=tenant)

    def create_task_manager(*, job_id: UUID) -> TaskManager:
        return TaskManager(
            user=user,
            job_id=job_id,
            channel_type=ChannelType.APP_RUN_UPDATES,
        )

    container.task_manager.override(providers.Callable(create_task_manager))
    container.text_extractor.override(providers.Object(StubExtractor()))
    container.group_service.override(
        providers.Object(
            SimpleNamespace(
                get_group=AsyncMock(
                    return_value=SimpleNamespace(embedding_model=object())
                )
            )
        )
    )
    container.text_processor.override(
        providers.Object(SimpleNamespace(process_text=process_text))
    )
    task = asyncio.create_task(
        upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=uuid4(),
                space_id=uuid4(),
                filename="replacement.txt",
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=container,
        )
    )
    compute_waiter = asyncio.create_task(compute_started.wait())
    done, _ = await asyncio.wait(
        {task, compute_waiter},
        timeout=5,
        return_when=asyncio.FIRST_COMPLETED,
    )
    assert done
    if task in done:
        await task
    assert compute_waiter in done

    reaped_finished_at = datetime.now(timezone.utc)
    if reaped_before_cancel:
        async with sessionmanager.session() as session, session.begin():
            await session.execute(
                sa.update(Jobs)
                .where(Jobs.id == job_id)
                .values(
                    status=Status.FAILED.value,
                    result_location=None,
                    failure_code=JobFailureCode.PROCESSING_INTERRUPTED.value,
                    finished_at=reaped_finished_at,
                    updated_at=reaped_finished_at,
                )
            )

    if reaped_before_cancel:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert compute_cancelled.is_set()

    async with sessionmanager.session() as session, session.begin():
        status, result_location, failure_code, finished_at = (
            await session.execute(
                sa.select(
                    Jobs.status,
                    Jobs.result_location,
                    Jobs.failure_code,
                    Jobs.finished_at,
                ).where(Jobs.id == job_id)
            )
        ).one()
    published_statuses = [
        RedisMessage.model_validate_json(call.args[1]).status
        for call in redis_publish.await_args_list
    ]
    if reaped_before_cancel:
        assert (status, result_location, failure_code, finished_at) == (
            Status.FAILED.value,
            None,
            JobFailureCode.PROCESSING_INTERRUPTED.value,
            reaped_finished_at,
        )
        assert published_statuses == [Status.IN_PROGRESS]
        failure_log.assert_not_called()
    else:
        assert status == Status.FAILED.value
        assert result_location is None
        assert failure_code == JobFailureCode.CANCELLED.value
        assert finished_at is not None
        assert published_statuses == [Status.IN_PROGRESS, Status.FAILED]
        failure_log.assert_called_once_with(
            "Knowledge job failed",
            extra={
                "job_id": str(job_id),
                "task": Task.UPLOAD_FILE.value,
                "failure_code": JobFailureCode.CANCELLED.value,
            },
        )


async def test_reaper_only_fails_a_bounded_page_of_stale_in_progress_jobs(
    db_container,
) -> None:
    from eneo.jobs import job_repo

    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(minutes=10)
    fresh_id = uuid4()
    queued_id = uuid4()
    stale_ids = [uuid4() for _ in range(job_repo.KNOWLEDGE_REAPER_PAGE_SIZE + 2)]

    async with db_container() as setup:
        user = setup.user()
        setup.session().add_all(
            [
                Jobs(
                    id=job_id,
                    user_id=user.id,
                    task=(
                        Task.UPLOAD_FILE.value
                        if offset % 2 == 0
                        else Task.TRANSCRIPTION.value
                    ),
                    status=Status.IN_PROGRESS.value,
                    updated_at=stale_at,
                )
                for offset, job_id in enumerate(stale_ids)
            ]
            + [
                Jobs(
                    id=fresh_id,
                    user_id=user.id,
                    task=Task.UPLOAD_FILE.value,
                    status=Status.IN_PROGRESS.value,
                    updated_at=now,
                ),
                Jobs(
                    id=queued_id,
                    user_id=user.id,
                    task=Task.TRANSCRIPTION.value,
                    status=Status.QUEUED.value,
                    dispatch_envelope={"version": 1},
                    updated_at=stale_at,
                ),
            ]
        )

    async with sessionmanager.session() as session, session.begin():
        first = await JobRepository(session).mark_stale_in_progress_jobs_failed(
            now - job_repo.KNOWLEDGE_JOB_STALE_AFTER
        )
    async with sessionmanager.session() as session, session.begin():
        second = await JobRepository(session).mark_stale_in_progress_jobs_failed(
            now - job_repo.KNOWLEDGE_JOB_STALE_AFTER
        )

    assert len(first) == job_repo.KNOWLEDGE_REAPER_PAGE_SIZE
    assert len(second) == 2
    assert {job_id for job_id, _task in first + second} == set(stale_ids)
    assert {task for _job_id, task in first + second} == {
        Task.UPLOAD_FILE.value,
        Task.TRANSCRIPTION.value,
    }
    async with sessionmanager.session() as session, session.begin():
        rows = {
            row.id: (row.status, row.result_location, row.failure_code)
            for row in (
                await session.execute(
                    sa.select(
                        Jobs.id,
                        Jobs.status,
                        Jobs.result_location,
                        Jobs.failure_code,
                    ).where(Jobs.id.in_([*stale_ids, fresh_id, queued_id]))
                )
            ).all()
        }
    assert rows[fresh_id][0] == Status.IN_PROGRESS.value
    assert rows[queued_id][0] == Status.QUEUED.value
    assert all(
        rows[job_id]
        == (
            Status.FAILED.value,
            None,
            JobFailureCode.PROCESSING_INTERRUPTED.value,
        )
        for job_id in stale_ids
    )


async def test_reaper_logs_stable_failure_identity(db_container, monkeypatch) -> None:
    job_id = uuid4()
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with db_container() as setup:
        user = setup.user()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.TRANSCRIPTION.value,
                status=Status.IN_PROGRESS.value,
                updated_at=stale_at,
            )
        )

    failure_log = MagicMock()
    monkeypatch.setattr(
        worker_routes,
        "logger",
        SimpleNamespace(warning=failure_log),
    )

    await worker_routes.reap_stale_knowledge_jobs({})

    failure_log.assert_called_once_with(
        "Stale knowledge job failed",
        extra={
            "job_id": str(job_id),
            "task": Task.TRANSCRIPTION.value,
            "failure_code": JobFailureCode.PROCESSING_INTERRUPTED.value,
        },
    )


def _write_old_staging_file(path: Path, *, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"staged")
    old_timestamp = (now - timedelta(hours=2)).timestamp()
    os.utime(path, (old_timestamp, old_timestamp))


async def test_staging_reconciler_recovers_terminal_files_and_reaches_orphans(
    db_container, tmp_path, monkeypatch
) -> None:
    from eneo.jobs import job_staging

    monkeypatch.setattr(
        job_staging,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    now = datetime.now(timezone.utc)
    complete_id = uuid4()
    failed_id = uuid4()
    active_ids = [uuid4() for _ in range(job_staging.STAGING_RECONCILE_PAGE_SIZE)]
    orphan_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        setup.session().add_all(
            [
                Jobs(
                    id=complete_id,
                    user_id=user.id,
                    task=Task.UPLOAD_FILE.value,
                    status=Status.COMPLETE.value,
                    dispatch_envelope={"version": 1},
                    finished_at=now,
                ),
                Jobs(
                    id=failed_id,
                    user_id=user.id,
                    task=Task.TRANSCRIPTION.value,
                    status=Status.FAILED.value,
                    dispatch_envelope={"version": 1},
                    finished_at=now,
                ),
                *[
                    Jobs(
                        id=job_id,
                        user_id=user.id,
                        task=Task.UPLOAD_FILE.value,
                        status=Status.IN_PROGRESS.value,
                        dispatch_envelope={"version": 1},
                    )
                    for job_id in active_ids
                ],
            ]
        )

    paths = {
        job_id: job_staging.job_staging_path(job_id)
        for job_id in [complete_id, failed_id, *active_ids, orphan_id]
    }
    for path in paths.values():
        _write_old_staging_file(path, now=now)

    async with sessionmanager.session() as session, session.begin():
        result = await job_staging.reconcile_job_staging(session, now=now)

    assert result.terminal_cleaned == 2
    assert result.orphans_deleted == 1
    assert not paths[complete_id].exists()
    assert not paths[failed_id].exists()
    assert not paths[orphan_id].exists()
    assert all(paths[job_id].exists() for job_id in active_ids)
    async with sessionmanager.session() as session, session.begin():
        cleaned = dict(
            (
                await session.execute(
                    sa.select(Jobs.id, Jobs.staging_cleaned_at).where(
                        Jobs.id.in_([complete_id, failed_id, *active_ids])
                    )
                )
            ).all()
        )
    assert cleaned[complete_id] is not None
    assert cleaned[failed_id] is not None
    assert all(cleaned[job_id] is None for job_id in active_ids)


async def test_orphan_sweep_offloads_discovery_and_batches_database_queries(
    db_container, tmp_path, monkeypatch
) -> None:
    from eneo.jobs import job_staging

    query_batch_size = 4
    delete_limit = 3
    monkeypatch.setattr(
        job_staging,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    monkeypatch.setattr(
        job_staging,
        "ORPHAN_STAGING_QUERY_BATCH_SIZE",
        query_batch_size,
        raising=False,
    )
    monkeypatch.setattr(
        job_staging,
        "ORPHAN_STAGING_DELETE_LIMIT",
        delete_limit,
    )
    now = datetime.now(timezone.utc)
    existing_ids = [uuid4() for _ in range(query_batch_size * 2 + 1)]
    orphan_ids = [uuid4() for _ in range(delete_limit + 1)]
    async with db_container() as setup:
        user = setup.user()
        setup.session().add_all(
            [
                Jobs(
                    id=job_id,
                    user_id=user.id,
                    task=Task.UPLOAD_FILE.value,
                    status=Status.IN_PROGRESS.value,
                )
                for job_id in existing_ids
            ]
        )

    paths = [
        job_staging.job_staging_path(job_id) for job_id in [*existing_ids, *orphan_ids]
    ]
    for path in paths:
        _write_old_staging_file(path, now=now)

    staging_directory = paths[0].parent
    original_iterdir = Path.iterdir
    discovery_started = threading.Event()
    allow_discovery = threading.Event()
    event_loop_progressed = asyncio.Event()

    def ordered_iterdir(self: Path):
        if self != staging_directory:
            return original_iterdir(self)
        discovery_started.set()
        assert allow_discovery.wait(timeout=1)
        return iter(paths)

    async def release_discovery() -> None:
        while not discovery_started.is_set():
            await asyncio.sleep(0)
        event_loop_progressed.set()
        allow_discovery.set()

    monkeypatch.setattr(Path, "iterdir", ordered_iterdir)
    release_task = asyncio.create_task(release_discovery())
    query_sizes: list[int] = []
    async with sessionmanager.session() as session, session.begin():
        assert session.bind is not None
        sync_engine = session.bind.sync_engine

        def capture_query_size(
            _connection,
            _cursor,
            statement,
            parameters,
            _context,
            _executemany,
        ) -> None:
            if "WHERE jobs.id IN" in statement:
                query_sizes.append(len(parameters))

        sa.event.listen(sync_engine, "before_cursor_execute", capture_query_size)
        try:
            result = await job_staging.reconcile_job_staging(session, now=now)
        finally:
            sa.event.remove(
                sync_engine,
                "before_cursor_execute",
                capture_query_size,
            )
            await release_task

    assert event_loop_progressed.is_set()
    assert query_sizes
    assert max(query_sizes) <= query_batch_size
    assert result.orphans_deleted == delete_limit
    assert not job_staging.job_staging_path(orphan_ids[0]).exists()
    assert job_staging.job_staging_path(orphan_ids[-1]).exists()
    assert all(job_staging.job_staging_path(job_id).exists() for job_id in existing_ids)


async def test_staging_reconciler_retries_failed_unlink(
    db_container, tmp_path, monkeypatch
) -> None:
    from eneo.jobs import job_staging

    monkeypatch.setattr(
        job_staging,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    now = datetime.now(timezone.utc)
    job_id = uuid4()
    async with db_container() as setup:
        user = setup.user()
        setup.session().add(
            Jobs(
                id=job_id,
                user_id=user.id,
                task=Task.UPLOAD_FILE.value,
                status=Status.FAILED.value,
                dispatch_envelope={"version": 1},
                finished_at=now,
            )
        )
    path = job_staging.job_staging_path(job_id)
    _write_old_staging_file(path, now=now)
    original_unlink = Path.unlink

    def fail_target_unlink(self: Path, *args, **kwargs):
        if self == path:
            raise OSError("volume unavailable")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_target_unlink)
    async with sessionmanager.session() as session, session.begin():
        result = await job_staging.reconcile_job_staging(session, now=now)

    assert result.terminal_cleaned == 0
    assert path.exists()
    async with sessionmanager.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(Jobs.staging_cleaned_at).where(Jobs.id == job_id)
            )
            is None
        )


async def test_staging_reconciler_limits_terminal_database_page(
    db_container, tmp_path, monkeypatch
) -> None:
    from eneo.jobs import job_staging

    monkeypatch.setattr(
        job_staging,
        "get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    now = datetime.now(timezone.utc)
    job_ids = [uuid4() for _ in range(job_staging.STAGING_RECONCILE_PAGE_SIZE + 1)]
    async with db_container() as setup:
        user = setup.user()
        setup.session().add_all(
            [
                Jobs(
                    id=job_id,
                    user_id=user.id,
                    task=Task.UPLOAD_FILE.value,
                    status=Status.COMPLETE.value,
                    dispatch_envelope={"version": 1},
                    finished_at=now,
                )
                for job_id in job_ids
            ]
        )
    for job_id in job_ids:
        _write_old_staging_file(job_staging.job_staging_path(job_id), now=now)

    async with sessionmanager.session() as session, session.begin():
        result = await job_staging.reconcile_job_staging(session, now=now)

    assert result.terminal_cleaned == job_staging.STAGING_RECONCILE_PAGE_SIZE
    async with sessionmanager.session() as session, session.begin():
        cleaned_count = await session.scalar(
            sa.select(sa.func.count())
            .select_from(Jobs)
            .where(Jobs.id.in_(job_ids), Jobs.staging_cleaned_at.is_not(None))
        )
    assert cleaned_count == job_staging.STAGING_RECONCILE_PAGE_SIZE
