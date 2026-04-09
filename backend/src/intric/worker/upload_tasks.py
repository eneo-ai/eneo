import contextlib
import os
from pathlib import Path
from uuid import UUID

from intric.jobs.task_models import Transcription, UploadInfoBlob
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException


def _remove_file(filepath: Path):
    with contextlib.suppress(FileNotFoundError):
        os.remove(filepath)


async def transcription_task(
    *,
    job_id: UUID,
    params: Transcription,
    container: Container,
):
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        filepath = Path(params.filepath)

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
        filepath = Path(params.filepath)

        # Define cleanup function
        task_manager.cleanup_func = lambda: _remove_file(filepath)

        uploader = container.text_processor()
        group_service = container.group_service()
        group = await group_service.get_group(params.group_id)
        embedding_model = group.embedding_model

        info_blob = await uploader.process_file(
            filepath=filepath,
            filename=params.filename,
            mimetype=params.mimetype,
            group_id=params.group_id,
            embedding_model=embedding_model,
        )
        assert info_blob is not None

        task_manager.result_location = f"/api/v1/info-blobs/{info_blob.id}/"

    return task_manager.successful()
