import asyncio
import contextlib
import os
from tempfile import SpooledTemporaryFile
from uuid import UUID

from eneo.admin.quota_service import QuotaService
from eneo.files.audio import AudioMimeTypes
from eneo.files.file_size_service import FileSizeService
from eneo.files.text import TextMimeTypes
from eneo.jobs.job_models import JobInDb, Task
from eneo.jobs.job_service import JobService
from eneo.jobs.task_models import TaskParams, Transcription, UploadInfoBlob
from eneo.main.config import get_settings
from eneo.main.exceptions import FileNotSupportedException, FileTooLargeException
from eneo.users.user import UserInDB
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import CrawlType


class TaskService:
    def __init__(
        self,
        user: UserInDB,
        file_size_service: FileSizeService,
        job_service: JobService,
        quota_service: QuotaService,
    ) -> None:
        super().__init__()
        self.user = user
        self.file_size_service = file_size_service
        self.job_service = job_service
        self.quota_service = quota_service

    @staticmethod
    def get_task_type(mimetype: str):
        if TextMimeTypes.has_value(mimetype):
            return Task.UPLOAD_FILE
        elif AudioMimeTypes.has_value(mimetype):
            return Task.TRANSCRIPTION
        else:
            raise FileNotSupportedException(f"{mimetype} not supported.")

    @staticmethod
    def get_max_size(task: Task):
        match task:
            case Task.UPLOAD_FILE:
                return get_settings().upload_max_file_size, "UPLOAD_MAX_FILE_SIZE"
            case Task.TRANSCRIPTION:
                return (
                    get_settings().transcription_max_file_size,
                    "TRANSCRIPTION_MAX_FILE_SIZE",
                )
            case _:
                return 0, None

    async def validate_file_size(
        self, file: SpooledTemporaryFile[bytes], task: Task
    ) -> None:
        max_size, setting_name = self.get_max_size(task)
        file_size = await asyncio.to_thread(self.file_size_service.get_file_size, file)

        if file_size > max_size:
            raise FileTooLargeException(
                file_size=file_size,
                max_size=max_size,
                setting_name=setting_name,
            )

    async def ensure_quota(self, file: SpooledTemporaryFile[bytes], task: Task) -> None:
        if task not in (Task.UPLOAD_FILE, Task.TRANSCRIPTION):
            return

        file_size = await asyncio.to_thread(self.file_size_service.get_file_size, file)
        await self.quota_service.ensure_capacity(file_size)

    async def queue_upload_file(
        self,
        group_id: UUID,
        space_id: UUID,
        file: SpooledTemporaryFile[bytes],
        mimetype: str,
        filename: str,
    ):
        task_type = self.get_task_type(mimetype)

        await self.validate_file_size(file, task_type)
        await self.ensure_quota(file, task_type)

        filepath = await self.file_size_service.save_file_to_disk(file)

        try:
            if task_type == Task.UPLOAD_FILE:
                params: TaskParams = UploadInfoBlob(
                    filepath=filepath,
                    filename=filename,
                    user_id=self.user.id,
                    group_id=group_id,
                    space_id=space_id,
                    mimetype=mimetype,
                )
            else:
                # task_type == Task.TRANSCRIPTION (get_task_type raises for any other value)
                params = Transcription(
                    filepath=filepath,
                    filename=filename,
                    user_id=self.user.id,
                    group_id=group_id,
                    space_id=space_id,
                    mimetype=mimetype,
                )

            # Set name of the job to the filename being processed
            job = await self.job_service.queue_job(
                task_type, name=filename, task_params=params
            )
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.remove(filepath)
            raise

        return job

    async def queue_crawl(
        self,
        name: str,
        run_id: UUID,
        url: str,
        download_files: bool = False,
        crawl_type: CrawlType = CrawlType.CRAWL,
        website_id: UUID | None = None,
        enqueue: bool = True,
    ) -> JobInDb:
        # CrawlTask.website_id is UUID (non-optional); callers always provide a value
        assert website_id is not None, "website_id is required for crawl tasks"
        params = CrawlTask(
            user_id=self.user.id,
            run_id=run_id,
            url=url,
            download_files=download_files,
            crawl_type=crawl_type,
            website_id=website_id,
        )

        return await self.job_service.queue_job(
            Task.CRAWL, name=name, task_params=params, enqueue=enqueue
        )
