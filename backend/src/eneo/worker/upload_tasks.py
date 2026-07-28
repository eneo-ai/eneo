import contextlib
import os
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.files.text import NoExtractableTextError
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import Transcription, UploadInfoBlob
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException


def _remove_file(filepath: Path):
    with contextlib.suppress(FileNotFoundError):
        os.remove(filepath)


def _job_file_path(job_id: UUID, params: UploadInfoBlob | Transcription) -> Path:
    # Remove after the next release once the ARQ queue TTL and rollback window pass.
    legacy_path = getattr(params, "filepath", None)
    if isinstance(legacy_path, str) and legacy_path.strip():
        return Path(legacy_path)
    return job_staging_path(job_id)


async def transcription_task(
    *,
    job_id: UUID,
    params: Transcription,
    container: Container,
):
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        filepath = _job_file_path(job_id, params)

        # Define cleanup function
        task_manager.cleanup_func = lambda: _remove_file(filepath)

        # Get the space
        space_service = container.space_service()
        space = await space_service.get_space(params.space_id)

        # Get the transcription model from the space
        transcription_model = space.get_default_transcription_model()

        # If the space doesn't have any transcription models, fail the job
        if transcription_model is None:
            raise BadRequestException("No transcription model enabled in the space.")

        transcriber = container.transcriber()
        uploader = container.text_processor()
        group_service = container.group_service()
        group = await group_service.get_group(params.group_id)
        embedding_model = group.embedding_model

        text = await transcriber.transcribe_from_filepath(
            filepath=filepath, transcription_model=transcription_model
        )
        if not text.strip():
            raise NoExtractableTextError(params.filename)

        # Keep knowledge publication atomic while job status uses the ambient transaction.
        session = cast(AsyncSession, container.session())
        async with session.begin_nested():
            info_blob = await uploader.process_text(
                text=text,
                embedding_model=embedding_model,
                title=params.filename,
                group_id=params.group_id,
            )
        assert info_blob is not None

        task_manager.result_location = f"/api/v1/info-blobs/{info_blob.id}/"

    return task_manager.successful()


async def upload_info_blob_task(
    *,
    job_id: UUID,
    params: UploadInfoBlob,
    container: Container,
):
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        filepath = _job_file_path(job_id, params)

        # Define cleanup function
        task_manager.cleanup_func = lambda: _remove_file(filepath)

        uploader = container.text_processor()
        group_service = container.group_service()
        group = await group_service.get_group(params.group_id)
        embedding_model = group.embedding_model

        text = container.text_extractor().extract(
            filepath, params.mimetype, params.filename
        )
        if not text.strip():
            raise NoExtractableTextError(params.filename)

        session = cast(AsyncSession, container.session())
        async with session.begin_nested():
            info_blob = await uploader.process_text(
                text=text,
                embedding_model=embedding_model,
                title=params.filename,
                group_id=params.group_id,
            )
        assert info_blob is not None

        task_manager.result_location = f"/api/v1/info-blobs/{info_blob.id}/"

    return task_manager.successful()
