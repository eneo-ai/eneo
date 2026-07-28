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
from eneo.database.tables.spaces_table import Spaces, SpacesTranscriptionModels
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.files.chunk_embedding_list import ChunkEmbeddingList
from eneo.jobs.job_models import Task
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import Transcription, UploadInfoBlob
from eneo.main.models import Status
from eneo.worker.upload_tasks import transcription_task, upload_info_blob_task

TITLE = "stable-knowledge.txt"
OLD_TEXT = "Previously published knowledge that must remain searchable."
OLD_CHUNKS = (
    (0, "Previously published knowledge", [0.1, 0.2, 0.3]),
    (1, "that must remain searchable.", [0.4, 0.5, 0.6]),
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


async def _seed_attempt(container, *, with_existing: bool = True):
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
        task=Task.UPLOAD_FILE.value,
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


async def _committed_state(job_id: UUID):
    async with sessionmanager.session() as session, session.begin():
        job_state = (
            await session.execute(
                sa.select(Jobs.status, Jobs.result_location).where(Jobs.id == job_id)
            )
        ).one()
        blobs = (
            await session.scalars(
                sa.select(InfoBlobs).where(
                    InfoBlobs.title == TITLE,
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
        _stage_job_file(tmp_path, job_id, b"replacement")
        extracted: str | Exception = "replacement knowledge"
        if failure == "extraction":
            extracted = RuntimeError("extraction failed")
        elif failure == "blank":
            extracted = " \n\t "
        container.text_extractor.override(providers.Object(StubExtractor(extracted)))
        if failure in {"embedding", "blank"}:
            embeddings = AsyncMock()
            embeddings.get_embeddings.side_effect = RuntimeError("embedding failed")
            container.create_embeddings_service.override(providers.Object(embeddings))
        if failure == "chunking":
            monkeypatch.setattr(
                Datastore,
                "_chunk_text",
                lambda self, info_blob: (_ for _ in ()).throw(
                    RuntimeError("chunking failed")
                ),
            )
        result = await upload_info_blob_task(
            job_id=job.id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group.id,
                space_id=space.id,
                filename=TITLE,
                mimetype="text/plain",
            ),
            container=container,
        )
        assert result is False

    (status, error), blobs, chunks = await _committed_state(job_id)
    assert status == Status.FAILED.value
    if failure == "blank":
        assert error == f"File '{TITLE}' contains no extractable text"
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
        _stage_job_file(tmp_path, job_id, b"replacement")
        container.text_extractor.override(
            providers.Object(
                StubExtractor(" \n " if failure == "blank" else "replacement knowledge")
            )
        )
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = RuntimeError("embedding failed")
        container.create_embeddings_service.override(providers.Object(embeddings))
        result = await upload_info_blob_task(
            job_id=job.id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group.id,
                space_id=space.id,
                filename=TITLE,
                mimetype="text/plain",
            ),
            container=container,
        )
        assert result is False

    (status, error), blobs, chunks = await _committed_state(job_id)
    assert status == Status.FAILED.value
    if failure == "blank":
        assert error == f"File '{TITLE}' contains no extractable text"
        embeddings.get_embeddings.assert_not_awaited()
    assert blobs == []
    assert chunks == []


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
        _stage_job_file(tmp_path, job_id, b"replacement")
        container.text_extractor.override(
            providers.Object(StubExtractor(replacement_text))
        )
        embeddings = AsyncMock()

        def embed(*, model, chunks):
            result = ChunkEmbeddingList()
            result.add(chunks, [[0.7, 0.8, 0.9] for _ in chunks])
            return result

        embeddings.get_embeddings.side_effect = embed
        container.create_embeddings_service.override(providers.Object(embeddings))

        result = await upload_info_blob_task(
            job_id=job.id,
            params=UploadInfoBlob(
                user_id=user.id,
                group_id=group.id,
                space_id=space.id,
                filename=TITLE,
                mimetype="text/plain",
            ),
            container=container,
        )
        assert result is True

    (status, result_location), blobs, chunks = await _committed_state(job_id)
    old_blob_id, _ = prior
    assert status == Status.COMPLETE.value
    assert len(blobs) == 1
    blob_id, text, size = blobs[0]
    assert blob_id != old_blob_id
    assert text == replacement_text
    assert size > 0
    assert result_location == f"/api/v1/info-blobs/{blob_id}/"
    assert [(chunk_no, text) for _, chunk_no, text, _ in chunks] == [
        (0, replacement_text)
    ]
    assert chunks[0][3] == _pgvector_values([0.7, 0.8, 0.9])


@pytest.mark.parametrize("failure", ["embedding", "blank"])
async def test_transcription_failure_preserves_committed_prior_knowledge(
    db_container, tmp_path, monkeypatch, transcription_model_factory, failure
):
    monkeypatch.setattr(
        "eneo.jobs.job_staging.get_settings",
        lambda: SimpleNamespace(upload_tmp_dir=tmp_path),
    )
    async with db_container() as container:
        user, space, group, job, prior = await _seed_attempt(container)
        job_id = job.id
        _stage_job_file(tmp_path, job_id, b"not used")
        transcription_model = await transcription_model_factory(
            container.session(), "ingestion-safety-transcription"
        )
        container.session().add(
            SpacesTranscriptionModels(
                space_id=space.id, transcription_model_id=transcription_model.id
            )
        )
        await container.session().flush()
        transcriber = AsyncMock()
        transcriber.transcribe_from_filepath.return_value = (
            " \n " if failure == "blank" else "replacement transcript"
        )
        container.transcriber.override(providers.Object(transcriber))
        embeddings = AsyncMock()
        embeddings.get_embeddings.side_effect = RuntimeError("embedding failed")
        container.create_embeddings_service.override(providers.Object(embeddings))

        result = await transcription_task(
            job_id=job.id,
            params=Transcription(
                user_id=user.id,
                group_id=group.id,
                space_id=space.id,
                filename=TITLE,
                mimetype="audio/wav",
            ),
            container=container,
        )
        assert result is False

    (status, error), blobs, chunks = await _committed_state(job_id)
    assert status == Status.FAILED.value
    if failure == "blank":
        assert error == f"File '{TITLE}' contains no extractable text"
        embeddings.get_embeddings.assert_not_awaited()
    _assert_prior_knowledge(prior, blobs, chunks)
