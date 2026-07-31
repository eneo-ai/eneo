import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from eneo.files.text import NoExtractableTextError
from eneo.info_blobs.info_blob import PreparedKnowledgeOriginal
from eneo.jobs.job_models import Task, failure_code_for_exception
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import Transcription, UploadInfoBlob
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger
from eneo.main.models import Status
from eneo.object_content.content import StorageKind
from eneo.worker.task_manager import TaskManager

KNOWLEDGE_HEARTBEAT_INTERVAL_SECONDS = 30
_STAGED_FILE_CHUNK_BYTES = 256 * 1024

logger = get_logger(__name__)


def _remove_file(filepath: Path):
    with contextlib.suppress(FileNotFoundError):
        os.remove(filepath)


async def _staged_file_chunks(filepath: Path) -> AsyncGenerator[bytes]:
    with filepath.open("rb") as source:
        while chunk := await asyncio.to_thread(
            source.read,
            _STAGED_FILE_CHUNK_BYTES,
        ):
            yield chunk


@asynccontextmanager
async def _prepared_knowledge_original(
    *,
    container: Container,
    job_id: UUID,
    filepath: Path,
    params: UploadInfoBlob | Transcription,
) -> AsyncGenerator[PreparedKnowledgeOriginal]:
    admission = params.original_storage
    object_content = container.object_content_service()
    media_type = params.mimetype or "application/octet-stream"
    async with object_content.capture_for_target(
        _staged_file_chunks(filepath),
        storage_kind=admission.storage_target,
        declared_media_type=media_type,
        verified_media_type=media_type,
        business_maximum_bytes=admission.maximum_bytes,
    ) as captured:
        if admission.storage_target is StorageKind.POSTGRES_INLINE:
            yield PreparedKnowledgeOriginal(
                job_id=job_id,
                original_filename=params.filename,
                policy_revision=admission.policy_revision,
                storage_kind=admission.storage_target,
                captured=captured,
            )
            return

        async with object_content.upload_for_publication((captured,)) as publication:
            yield PreparedKnowledgeOriginal(
                job_id=job_id,
                original_filename=params.filename,
                policy_revision=admission.policy_revision,
                storage_kind=admission.storage_target,
                captured=captured,
                publication=publication,
            )


async def _run_knowledge_heartbeat(
    container: Container,
    job_id: UUID,
    owner_task: asyncio.Task[object],
) -> None:
    while True:
        await asyncio.sleep(KNOWLEDGE_HEARTBEAT_INTERVAL_SECONDS)
        try:
            async with Container.session_scope():
                lease_live = await container.job_repo().touch_job(job_id)
        except Exception as exc:
            logger.warning(
                "Knowledge job heartbeat failed",
                extra={"job_id": str(job_id), "error": str(exc)},
            )
            continue
        if not lease_live:
            owner_task.cancel()
            return


@asynccontextmanager
async def _knowledge_heartbeat(container: Container, job_id: UUID):
    owner_task = asyncio.current_task()
    assert owner_task is not None
    heartbeat = asyncio.create_task(
        _run_knowledge_heartbeat(container, job_id, owner_task)
    )
    try:
        yield
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat


class _KnowledgeJobLifecycle:
    def __init__(
        self,
        *,
        container: Container,
        job_id: UUID,
        task: Task,
        task_manager: TaskManager,
    ) -> None:
        self.container = container
        self.job_id = job_id
        self.task = task
        self.task_manager = task_manager

    @classmethod
    async def start(
        cls,
        *,
        container: Container,
        job_id: UUID,
        task: Task,
    ) -> "_KnowledgeJobLifecycle | None":
        async with Container.session_scope():
            if not await container.job_repo().mark_job_started(job_id):
                return None

        return cls(
            container=container,
            job_id=job_id,
            task=task,
            task_manager=container.task_manager(
                job_id=job_id,
            ),
        )

    async def finalize(self, result_location: str) -> None:
        if not await self.container.job_repo().mark_job_completed(
            self.job_id,
            result_location,
        ):
            raise RuntimeError("Knowledge job is no longer in progress")
        self.task_manager.result_location = result_location

    async def _fail_if_running(self, exc: BaseException) -> None:
        failure_code = failure_code_for_exception(exc)

        self.task_manager.mark_job_handled()
        async with Container.session_scope():
            failed = (
                await self.container.job_repo().mark_knowledge_job_failed_if_running(
                    self.job_id,
                    failure_code,
                )
            )
        if failed:
            logger.warning(
                "Knowledge job failed",
                extra={
                    "job_id": str(self.job_id),
                    "task": self.task.value,
                    "failure_code": failure_code.value,
                },
            )
            await self.task_manager.publish_status(Status.FAILED)

    @asynccontextmanager
    async def process(self):
        async with self.task_manager.set_status_on_exception(status_already_set=True):
            try:
                await self.task_manager.publish_status(Status.IN_PROGRESS)
                async with _knowledge_heartbeat(self.container, self.job_id):
                    yield
            except (Exception, asyncio.CancelledError) as exc:
                await self._fail_if_running(exc)
                raise
            else:
                self.task_manager.mark_job_handled()
                await self.task_manager.publish_status(Status.COMPLETE)


async def transcription_task(
    *,
    job_id: UUID,
    params: Transcription,
    container: Container,
):
    lifecycle = await _KnowledgeJobLifecycle.start(
        container=container,
        job_id=job_id,
        task=Task.TRANSCRIPTION,
    )
    if lifecycle is None:
        return None

    filepath = job_staging_path(job_id)
    lifecycle.task_manager.cleanup_func = lambda: _remove_file(filepath)
    async with lifecycle.process():
        async with Container.session_scope():
            space_service = container.space_service()
            space = await space_service.get_space(params.space_id)

            transcription_model = space.get_default_transcription_model()

            if transcription_model is None:
                raise BadRequestException(
                    "No transcription model enabled in the space."
                )

            transcriber = container.transcriber()
            group_service = container.group_service()
            group = await group_service.get_group(params.group_id)
            embedding_model = group.embedding_model

            prepared_transcription = await transcriber.prepare_transcription(
                transcription_model
            )
        text = await transcriber.transcribe_prepared_from_filepath(
            filepath=filepath,
            adapter=prepared_transcription,
        )
        if not text.strip():
            raise NoExtractableTextError(params.filename)

        async with _prepared_knowledge_original(
            container=container,
            job_id=job_id,
            filepath=filepath,
            params=params,
        ) as original:
            async with Container.session_scope():
                uploader = container.text_processor()
                info_blob = await uploader.process_text(
                    text=text,
                    embedding_model=embedding_model,
                    title=params.filename,
                    group_id=params.group_id,
                    original=original,
                )
                result_location = f"/api/v1/info-blobs/{info_blob.id}/"
                await lifecycle.finalize(result_location)
        assert info_blob is not None

    return lifecycle.task_manager.successful()


async def upload_info_blob_task(
    *,
    job_id: UUID,
    params: UploadInfoBlob,
    container: Container,
):
    lifecycle = await _KnowledgeJobLifecycle.start(
        container=container,
        job_id=job_id,
        task=Task.UPLOAD_FILE,
    )
    if lifecycle is None:
        return None

    filepath = job_staging_path(job_id)
    lifecycle.task_manager.cleanup_func = lambda: _remove_file(filepath)
    async with lifecycle.process():
        async with Container.session_scope():
            group_service = container.group_service()
            group = await group_service.get_group(params.group_id)
            embedding_model = group.embedding_model

        text = await asyncio.to_thread(
            container.text_extractor().extract,
            filepath,
            params.mimetype,
            params.filename,
        )
        if not text.strip():
            raise NoExtractableTextError(params.filename)

        async with _prepared_knowledge_original(
            container=container,
            job_id=job_id,
            filepath=filepath,
            params=params,
        ) as original:
            async with Container.session_scope():
                uploader = container.text_processor()
                info_blob = await uploader.process_text(
                    text=text,
                    embedding_model=embedding_model,
                    title=params.filename,
                    group_id=params.group_id,
                    original=original,
                )
                result_location = f"/api/v1/info-blobs/{info_blob.id}/"
                await lifecycle.finalize(result_location)
        assert info_blob is not None

    return lifecycle.task_manager.successful()
