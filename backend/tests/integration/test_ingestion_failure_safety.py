import struct
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.info_blob_chunk_table import InfoBlobChunks
from eneo.database.tables.info_blobs_table import (
    InfoBlobs,
    InfoBlobVersionState,
    active_info_blob_version,
)
from eneo.database.tables.job_table import Jobs
from eneo.database.tables.object_content_table import (
    InfoBlobContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.database.tables.spaces_table import Spaces, SpacesTranscriptionModels
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.info_blobs.info_blob_service import InfoBlobService
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import (
    KnowledgeOriginalAdmission,
    Transcription,
    UploadInfoBlob,
)
from eneo.main.container.container import Container, SessionProxy
from eneo.main.models import Status
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import ContentState, StorageKind
from eneo.object_content.content_service import ObjectContentService
from eneo.worker.task_manager import TaskManager
from eneo.worker.upload_tasks import transcription_task, upload_info_blob_task

TITLE = "stable-knowledge.txt"
OLD_TEXT = "Previously published knowledge that must remain searchable."
OLD_CHUNKS = (
    (0, "Previously published knowledge", [0.1, 0.2, 0.3]),
    (1, "that must remain searchable.", [0.4, 0.5, 0.6]),
)


def _original_admission() -> KnowledgeOriginalAdmission:
    return KnowledgeOriginalAdmission(
        policy_revision=1,
        storage_target=StorageKind.POSTGRES_INLINE,
        maximum_bytes=1_000_000,
    )


def _stage_job_file(tmp_path: Path, job_id: UUID, content: bytes) -> None:
    path = job_staging_path(job_id, upload_tmp_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _pgvector_values(values: list[float]) -> list[float]:
    return [struct.unpack("f", struct.pack("f", value))[0] for value in values]


class StubExtractor:
    def __init__(self, result: str | Exception):
        self.result = result

    def extract(
        self, filepath: Path, mimetype: str, filename: str | None = None
    ) -> str:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def _seed_attempt(
    container,
    *,
    with_existing: bool = True,
    task: Task = Task.UPLOAD_FILE,
):
    session = container.session()
    user = container.user()
    embedding_model = (await session.scalars(sa.select(EmbeddingModels).limit(1))).one()
    space = Spaces(
        name="Ingestion safety space",
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    session.add(space)
    await session.flush()
    group = CollectionsTable(
        name="Ingestion safety group",
        size=0,
        user_id=user.id,
        tenant_id=user.tenant_id,
        embedding_model_id=embedding_model.id,
        space_id=space.id,
    )
    job = Jobs(
        id=uuid4(),
        user_id=user.id,
        task=task.value,
        status=Status.QUEUED.value,
    )
    session.add_all((group, job))
    await session.flush()

    prior = None
    if with_existing:
        blob = InfoBlobs(
            title=TITLE,
            text=OLD_TEXT,
            size=777,
            content_hash=sha256(OLD_TEXT.encode("utf-8")).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user.id,
            tenant_id=user.tenant_id,
            group_id=group.id,
            embedding_model_id=embedding_model.id,
        )
        session.add(blob)
        await session.flush()
        chunks = [
            InfoBlobChunks(
                info_blob_id=blob.id,
                tenant_id=user.tenant_id,
                chunk_no=chunk_no,
                text=text,
                size=len(text),
                embedding=embedding,
            )
            for chunk_no, text, embedding in OLD_CHUNKS
        ]
        session.add_all(chunks)
        await session.flush()
        prior = (
            blob.id,
            [
                (chunk.id, chunk_no, text, _pgvector_values(embedding))
                for chunk, (chunk_no, text, embedding) in zip(
                    chunks, OLD_CHUNKS, strict=True
                )
            ],
        )
    return user, space, group, job, prior


async def _committed_state(job_id: UUID, *, title: str = TITLE):
    async with sessionmanager.session() as session, session.begin():
        job_state = (
            await session.execute(
                sa.select(
                    Jobs.status,
                    Jobs.result_location,
                    Jobs.failure_code,
                ).where(Jobs.id == job_id)
            )
        ).one()
        blobs = (
            await session.scalars(
                sa.select(InfoBlobs).where(
                    InfoBlobs.title == title,
                    active_info_blob_version(),
                )
            )
        ).all()
        chunks = (
            await session.scalars(
                sa.select(InfoBlobChunks)
                .join(InfoBlobs)
                .where(active_info_blob_version())
                .order_by(InfoBlobChunks.chunk_no)
            )
        ).all()
        return (
            job_state,
            [(blob.id, blob.text, blob.size) for blob in blobs],
            [
                (chunk.id, chunk.chunk_no, chunk.text, list(chunk.embedding))
                for chunk in chunks
            ],
        )


def _assert_prior_knowledge(prior, blobs, chunks):
    blob_id, expected_chunks = prior
    assert blobs == [(blob_id, OLD_TEXT, 777)]
    assert chunks == expected_chunks


def _sessionless_container(
    *,
    user,
    tenant,
    object_content_settings: ObjectContentCoreSettings | None = None,
) -> Container:
    container = Container(
        session=providers.Object(SessionProxy()),
        user=providers.Object(user),
        tenant=providers.Object(tenant),
    )
    container.object_content_service.override(
        providers.Object(
            ObjectContentService(
                object_content_settings or ObjectContentCoreSettings(_env_file=None),
                sessionmanager,
            )
        )
    )
    return container


async def _seed_transcription_attempt(
    container,
    transcription_model_factory,
    *,
    with_existing: bool = False,
):
    user, space, group, job, prior = await _seed_attempt(
        container,
        with_existing=with_existing,
        task=Task.TRANSCRIPTION,
    )
    transcription_model = await transcription_model_factory(
        container.session(),
        f"ingestion-admission-{job.id}",
    )
    container.session().add(
        SpacesTranscriptionModels(
            space_id=space.id,
            transcription_model_id=transcription_model.id,
        )
    )
    await container.session().flush()
    return user, space, group, job, prior


@pytest.mark.parametrize(
    ("failure", "payload", "settings", "expected_code"),
    [
        (
            "retained quota",
            b"audio rejected by retained quota",
            None,
            JobFailureCode.QUOTA_EXCEEDED,
        ),
        (
            "worker storage ceiling",
            b"five!",
            ObjectContentCoreSettings(
                inline_maximum_bytes=4,
                inline_io_chunk_bytes=4,
                _env_file=None,
            ),
            JobFailureCode.STORAGE_LIMIT_EXCEEDED,
        ),
    ],
)
async def test_transcription_admission_failure_skips_provider_work(
    db_container,
    tmp_path,
    monkeypatch,
    transcription_model_factory,
    failure,
    payload,
    settings,
    expected_code,
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    async with db_container() as container:
        user, space, group, job, _ = await _seed_transcription_attempt(
            container,
            transcription_model_factory,
        )
        if failure == "retained quota":
            user.tenant.quota_limit = 0
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    _stage_job_file(tmp_path, job_id, payload)
    task_container = _sessionless_container(
        user=user,
        tenant=tenant,
        object_content_settings=settings,
    )
    transcriber = AsyncMock()
    transcriber.prepare_transcription.return_value = object()
    transcriber.transcribe_prepared_from_filepath.return_value = "never used"
    task_container.transcriber.override(providers.Object(transcriber))

    async with db_container():
        result = await transcription_task(
            job_id=job_id,
            params=Transcription(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename="meeting.wav",
                mimetype="audio/wav",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )

    assert result is False
    transcriber.prepare_transcription.assert_not_awaited()
    transcriber.transcribe_prepared_from_filepath.assert_not_awaited()
    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id,
        title="meeting.wav",
    )
    assert status == Status.FAILED.value
    assert result_location is None
    assert failure_code == expected_code.value
    assert blobs == []
    assert chunks == []


@pytest.mark.parametrize("failure", ["extraction", "chunking", "embedding", "blank"])
async def test_upload_failure_preserves_committed_prior_knowledge(
    db_container, tmp_path, monkeypatch, failure
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(container)
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    _stage_job_file(tmp_path, job_id, b"replacement")
    extracted: str | Exception = "replacement knowledge"
    if failure == "extraction":
        extracted = RuntimeError("extraction failed")
    elif failure == "blank":
        extracted = " \n\t "
    task_container = _sessionless_container(user=user, tenant=tenant)
    task_container.text_extractor.override(providers.Object(StubExtractor(extracted)))
    if failure in {"embedding", "blank"}:
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = RuntimeError("embedding failed")
        task_container.create_embeddings_service.override(providers.Object(embeddings))
    if failure == "chunking":
        monkeypatch.setattr(
            Datastore,
            "_chunk_text",
            lambda self, info_blob: (_ for _ in ()).throw(
                RuntimeError("chunking failed")
            ),
        )
    async with db_container():
        result = await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )
    assert result is False

    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    assert status == Status.FAILED.value
    assert result_location is None
    assert failure_code == (
        JobFailureCode.NO_EXTRACTABLE_TEXT.value
        if failure == "blank"
        else JobFailureCode.PROCESSING_FAILED.value
    )
    if failure == "blank":
        embeddings.get_embeddings.assert_not_awaited()
    _assert_prior_knowledge(prior, blobs, chunks)


@pytest.mark.parametrize("failure", ["embedding", "blank"])
async def test_first_upload_failure_publishes_no_knowledge(
    db_container, tmp_path, monkeypatch, failure
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    async with db_container() as container:
        user, space, group, job, _ = await _seed_attempt(container, with_existing=False)
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    _stage_job_file(tmp_path, job_id, b"replacement")
    task_container = _sessionless_container(user=user, tenant=tenant)
    task_container.text_extractor.override(
        providers.Object(
            StubExtractor(" \n " if failure == "blank" else "replacement knowledge")
        )
    )
    embeddings = AsyncMock()
    embeddings.get_embeddings.side_effect = RuntimeError("embedding failed")
    task_container.create_embeddings_service.override(providers.Object(embeddings))
    async with db_container():
        result = await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )
    assert result is False

    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    assert status == Status.FAILED.value
    assert result_location is None
    assert failure_code == (
        JobFailureCode.NO_EXTRACTABLE_TEXT.value
        if failure == "blank"
        else JobFailureCode.PROCESSING_FAILED.value
    )
    if failure == "blank":
        embeddings.get_embeddings.assert_not_awaited()
    assert blobs == []
    assert chunks == []


async def test_worker_uses_lower_live_inline_ceiling_and_reports_storage_limit(
    db_container,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(container)
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    staged_path = job_staging_path(job_id, upload_tmp_dir=tmp_path)
    _stage_job_file(tmp_path, job_id, b"five!")
    task_container = _sessionless_container(user=user, tenant=tenant)
    task_container.text_extractor.override(
        providers.Object(StubExtractor("replacement knowledge"))
    )
    task_container.object_content_service.override(
        providers.Object(
            ObjectContentService(
                ObjectContentCoreSettings(
                    _env_file=None,
                    inline_maximum_bytes=4,
                    inline_io_chunk_bytes=4,
                ),
                sessionmanager,
            )
        )
    )

    async with db_container():
        result = await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="text/plain",
                original_storage=KnowledgeOriginalAdmission(
                    policy_revision=1,
                    storage_target=StorageKind.POSTGRES_INLINE,
                    maximum_bytes=100,
                ),
            ),
            container=task_container,
        )

    assert result is False
    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    assert status == Status.FAILED.value
    assert result_location is None
    assert failure_code == JobFailureCode.STORAGE_LIMIT_EXCEEDED.value
    assert not staged_path.exists()
    _assert_prior_knowledge(prior, blobs, chunks)


async def test_successful_upload_commits_replacement_knowledge(
    db_container, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    replacement_text = "Committed replacement knowledge"
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(container)
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    _stage_job_file(tmp_path, job_id, b"replacement")
    task_container = _sessionless_container(user=user, tenant=tenant)
    task_container.text_extractor.override(
        providers.Object(StubExtractor(replacement_text))
    )
    embeddings = AsyncMock()

    def embed(*, model, chunks):
        result = ChunkEmbeddingList()
        result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
        return result

    embeddings.get_embeddings.side_effect = embed
    task_container.create_embeddings_service.override(providers.Object(embeddings))

    async with db_container():
        result = await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )
    assert result is True

    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    old_blob_id, _ = prior
    assert status == Status.COMPLETE.value
    assert len(blobs) == 1
    blob_id, text, size = blobs[0]
    assert blob_id != old_blob_id
    assert text == replacement_text
    assert size > 0
    assert result_location == f"/api/v1/info-blobs/{blob_id}/"
    assert failure_code is None
    assert [(chunk_no, text) for _, chunk_no, text, _ in chunks] == [
        (0, replacement_text)
    ]
    assert chunks[0][3] == _pgvector_values([0.7, 0.8, 0.9])
    async with sessionmanager.session() as session, session.begin():
        reference = (
            await session.execute(
                sa.select(
                    InfoBlobContentReferences.original_filename,
                    ObjectContents.sha256,
                    ObjectContents.size_bytes,
                    InlineContentPayloads.payload,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .join(
                    InlineContentPayloads,
                    InlineContentPayloads.content_id == ObjectContents.id,
                )
                .where(InfoBlobContentReferences.info_blob_id == blob_id)
            )
        ).one()
    assert reference.original_filename == TITLE
    assert reference.sha256 == sha256(b"replacement").digest()
    assert reference.size_bytes == len(b"replacement")
    assert reference.payload == b"replacement"


async def test_reaped_job_cannot_publish_or_report_success(
    db_container, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    replacement_text = "Replacement that must roll back"
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(container)
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    original_publish = InfoBlobService.publish_info_blob_without_validation
    reaped_finished_at = None

    async def publish_then_reap(
        self,
        info_blob,
        *,
        embedding_model,
        original=None,
    ):
        nonlocal reaped_finished_at
        published = await original_publish(
            self,
            info_blob,
            embedding_model=embedding_model,
            original=original,
        )
        async with sessionmanager.session() as session, session.begin():
            reaped_finished_at = (
                await session.execute(
                    sa.update(Jobs)
                    .where(Jobs.id == job_id)
                    .values(
                        status=Status.FAILED.value,
                        finished_at=sa.func.now(),
                        result_location=None,
                        failure_code=JobFailureCode.PROCESSING_INTERRUPTED.value,
                    )
                    .returning(Jobs.finished_at)
                )
            ).scalar_one()
        return published

    monkeypatch.setattr(
        InfoBlobService,
        "publish_info_blob_without_validation",
        publish_then_reap,
    )
    _stage_job_file(tmp_path, job_id, b"replacement")
    task_container = _sessionless_container(user=user, tenant=tenant)
    task_container.text_extractor.override(
        providers.Object(StubExtractor(replacement_text))
    )
    embeddings = AsyncMock()

    def embed(*, model, chunks):
        result = ChunkEmbeddingList()
        result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
        return result

    embeddings.get_embeddings.side_effect = embed
    task_container.create_embeddings_service.override(providers.Object(embeddings))

    async with db_container():
        result = await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )

    assert result is False
    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    assert status == Status.FAILED.value
    assert result_location is None
    assert failure_code == JobFailureCode.PROCESSING_INTERRUPTED.value
    async with sessionmanager.session() as session, session.begin():
        finished_at = await session.scalar(
            sa.select(Jobs.finished_at).where(Jobs.id == job_id)
        )
    assert finished_at == reaped_finished_at
    _assert_prior_knowledge(prior, blobs, chunks)


async def test_complete_status_publication_failure_preserves_committed_knowledge(
    db_container, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    replacement_text = "Committed replacement knowledge"
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(container)
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()

    original_publish_status = TaskManager.publish_status

    async def fail_complete_status(self, status):
        if status == Status.COMPLETE:
            raise RuntimeError("status publication failed")
        await original_publish_status(self, status)

    monkeypatch.setattr(TaskManager, "publish_status", fail_complete_status)
    _stage_job_file(tmp_path, job_id, b"replacement")
    task_container = _sessionless_container(user=user, tenant=tenant)
    task_container.text_extractor.override(
        providers.Object(StubExtractor(replacement_text))
    )
    embeddings = AsyncMock()

    def embed(*, model, chunks):
        result = ChunkEmbeddingList()
        result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
        return result

    embeddings.get_embeddings.side_effect = embed
    task_container.create_embeddings_service.override(providers.Object(embeddings))

    async with db_container():
        result = await upload_info_blob_task(
            job_id=job_id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="text/plain",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )

    assert result is False
    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    old_blob_id, _ = prior
    assert status == Status.COMPLETE.value
    assert len(blobs) == 1
    blob_id, text, _ = blobs[0]
    assert blob_id != old_blob_id
    assert text == replacement_text
    assert result_location == f"/api/v1/info-blobs/{blob_id}/"
    assert failure_code is None
    assert [(chunk_no, text) for _, chunk_no, text, _ in chunks] == [
        (0, replacement_text)
    ]


@pytest.mark.parametrize("failure", ["embedding", "blank"])
async def test_transcription_failure_preserves_committed_prior_knowledge(
    db_container, tmp_path, monkeypatch, transcription_model_factory, failure
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(
            container,
            task=Task.TRANSCRIPTION,
        )
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()
        transcription_model = await transcription_model_factory(
            container.session(), "ingestion-safety-transcription"
        )
        container.session().add(
            SpacesTranscriptionModels(
                space_id=space.id, transcription_model_id=transcription_model.id
            )
        )
        await container.session().flush()

    _stage_job_file(tmp_path, job_id, b"not used")
    task_container = _sessionless_container(user=user, tenant=tenant)
    transcriber = AsyncMock()
    transcriber.prepare_transcription.return_value = object()
    transcriber.transcribe_prepared_from_filepath.return_value = (
        " \n " if failure == "blank" else "replacement transcript"
    )
    task_container.transcriber.override(providers.Object(transcriber))
    embeddings = AsyncMock()
    embeddings.get_embeddings.side_effect = RuntimeError("embedding failed")
    task_container.create_embeddings_service.override(providers.Object(embeddings))

    async with db_container():
        result = await transcription_task(
            job_id=job_id,
            params=Transcription(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename=TITLE,
                mimetype="audio/wav",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )
    assert result is False

    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id
    )
    assert status == Status.FAILED.value
    assert result_location is None
    assert failure_code == (
        JobFailureCode.NO_EXTRACTABLE_TEXT.value
        if failure == "blank"
        else JobFailureCode.PROCESSING_FAILED.value
    )
    if failure == "blank":
        embeddings.get_embeddings.assert_not_awaited()
    _assert_prior_knowledge(prior, blobs, chunks)


async def test_transcription_retains_original_and_repairs_retry_at_full_quota(
    db_container,
    tmp_path,
    monkeypatch,
    transcription_model_factory,
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    audio_payload = b"exact audio upload bytes"
    transcript = "Committed replacement transcript"
    async with db_container() as container:
        user, space, group, job, _ = await _seed_attempt(
            container,
            with_existing=False,
            task=Task.TRANSCRIPTION,
        )
        job_id = job.id
        group_id = group.id
        space_id = space.id
        tenant = container.tenant()
        transcription_model = await transcription_model_factory(
            container.session(),
            "successful-original-transcription",
        )
        container.session().add(
            SpacesTranscriptionModels(
                space_id=space.id,
                transcription_model_id=transcription_model.id,
            )
        )
        await container.session().flush()

    _stage_job_file(tmp_path, job_id, audio_payload)
    task_container = _sessionless_container(user=user, tenant=tenant)
    transcriber = AsyncMock()
    transcriber.prepare_transcription.return_value = object()
    transcriber.transcribe_prepared_from_filepath.return_value = transcript
    task_container.transcriber.override(providers.Object(transcriber))
    embeddings = AsyncMock()

    def embed(*, model, chunks):
        result = ChunkEmbeddingList()
        result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
        return result

    embeddings.get_embeddings.side_effect = embed
    task_container.create_embeddings_service.override(providers.Object(embeddings))

    async with db_container():
        result = await transcription_task(
            job_id=job_id,
            params=Transcription(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename="meeting.wav",
                mimetype="audio/wav",
                original_storage=_original_admission(),
            ),
            container=task_container,
        )

    assert result is True
    (status, result_location, failure_code), blobs, chunks = await _committed_state(
        job_id,
        title="meeting.wav",
    )
    assert status == Status.COMPLETE.value
    assert failure_code is None
    assert len(blobs) == 1
    blob_id, text, _ = blobs[0]
    assert text == transcript
    assert result_location == f"/api/v1/info-blobs/{blob_id}/"
    assert [(chunk_no, text) for _, chunk_no, text, _ in chunks] == [(0, transcript)]

    async with sessionmanager.session() as session, session.begin():
        reference = (
            await session.execute(
                sa.select(
                    ObjectContents.id.label("content_id"),
                    InfoBlobContentReferences.original_filename,
                    ObjectContents.sha256,
                    ObjectContents.size_bytes,
                    ObjectContents.declared_media_type,
                    ObjectContents.verified_media_type,
                    InlineContentPayloads.payload,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .join(
                    InlineContentPayloads,
                    InlineContentPayloads.content_id == ObjectContents.id,
                )
                .where(InfoBlobContentReferences.info_blob_id == blob_id)
            )
        ).one()
    assert reference.original_filename == "meeting.wav"
    assert reference.sha256 == sha256(audio_payload).digest()
    assert reference.size_bytes == len(audio_payload)
    assert reference.declared_media_type == "audio/wav"
    assert reference.verified_media_type == "audio/wav"
    assert reference.payload == audio_payload

    async with db_container(user=user, tenant=tenant) as container:
        retained_before = await container.info_blob_repo().get_retained_size_of_tenant(
            user.tenant_id
        )
        await container.session().execute(
            sa.update(ObjectContents)
            .where(ObjectContents.id == reference.content_id)
            .values(
                state=ContentState.FAILED.value,
                failure_code="backend_missing",
                failure_detail="test repair",
            )
        )
        retry_job = Jobs(
            id=uuid4(),
            user_id=user.id,
            task=Task.TRANSCRIPTION.value,
            status=Status.QUEUED.value,
        )
        container.session().add(retry_job)
        await container.session().flush()
        retry_job_id = retry_job.id
    user.tenant.quota_limit = retained_before

    _stage_job_file(tmp_path, retry_job_id, audio_payload)
    retry_container = _sessionless_container(user=user, tenant=tenant)
    retry_transcriber = AsyncMock()
    retry_transcriber.prepare_transcription.return_value = object()
    retry_transcriber.transcribe_prepared_from_filepath.return_value = transcript
    retry_container.transcriber.override(providers.Object(retry_transcriber))
    retry_embeddings = AsyncMock()
    retry_embeddings.get_embeddings.side_effect = embed
    retry_container.create_embeddings_service.override(
        providers.Object(retry_embeddings)
    )

    async with db_container():
        retry_result = await transcription_task(
            job_id=retry_job_id,
            params=Transcription(
                user_id=user.id,
                group_id=group_id,
                space_id=space_id,
                filename="meeting.wav",
                mimetype="audio/wav",
                original_storage=_original_admission(),
            ),
            container=retry_container,
        )

    assert retry_result is True
    retry_transcriber.transcribe_prepared_from_filepath.assert_awaited_once()
    retry_embeddings.get_embeddings.assert_not_awaited()
    async with db_container(user=user, tenant=tenant) as container:
        repaired_reference = (
            await container.session().execute(
                sa.select(
                    InfoBlobContentReferences.content_id,
                    ObjectContents.sha256,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == InfoBlobContentReferences.content_id,
                )
                .where(InfoBlobContentReferences.info_blob_id == blob_id)
            )
        ).one()
        failed_original = await container.session().get(
            ObjectContents,
            reference.content_id,
        )
        assert failed_original is not None
        await container.session().refresh(failed_original)
        failed_reference_count = failed_original.reference_count
        failed_delete_requested_at = failed_original.delete_requested_at
        retry_status = await container.session().scalar(
            sa.select(Jobs.status).where(Jobs.id == retry_job_id)
        )
        retained_after = await container.info_blob_repo().get_retained_size_of_tenant(
            user.tenant_id
        )

    assert repaired_reference.content_id != reference.content_id
    assert repaired_reference.sha256 == reference.sha256
    assert failed_reference_count == 0
    assert failed_delete_requested_at is not None
    assert retry_status == Status.COMPLETE.value
    assert retained_after == retained_before
