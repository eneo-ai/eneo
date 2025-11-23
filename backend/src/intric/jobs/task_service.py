import asyncio
from tempfile import SpooledTemporaryFile
from uuid import UUID

from intric.admin.quota_service import QuotaService
from intric.files.audio import AudioMimeTypes
from intric.files.file_size_service import FileSizeService
from intric.files.text import TextMimeTypes
from intric.jobs.job_models import JobInDb, Task
from intric.jobs.job_service import JobService
from intric.jobs.task_models import Transcription, UploadInfoBlob
from intric.main.config import get_settings
from intric.main.exceptions import FileNotSupportedException, FileTooLargeException
from intric.users.user import UserInDB
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_run import CrawlType


class TaskService:
    def __init__(
        self,
        user: UserInDB,
        file_size_service: FileSizeService,
        job_service: JobService,
        quota_service: QuotaService,
    ):
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
                return get_settings().upload_max_file_size
            case Task.TRANSCRIPTION:
                return get_settings().transcription_max_file_size
            case _:
                return 0

    async def validate_file_size(self, file: SpooledTemporaryFile, task: Task):
        max_size = self.get_max_size(task)

        if await asyncio.to_thread(self.file_size_service.is_too_large, file, max_size):
            raise FileTooLargeException("File too large.")

    async def ensure_quota(self, file: SpooledTemporaryFile, task: Task):
        if task not in (Task.UPLOAD_FILE, Task.TRANSCRIPTION):
            return

        file_size = await asyncio.to_thread(self.file_size_service.get_file_size, file)
        await self.quota_service.ensure_capacity(file_size)

    async def queue_upload_file(
        self,
        group_id: UUID,
        space_id: UUID,
        file: SpooledTemporaryFile,
        mimetype: str,
        filename: str,
    ):
        task_type = self.get_task_type(mimetype)

        await self.validate_file_size(file, task_type)
        await self.ensure_quota(file, task_type)

        filepath = await self.file_size_service.save_file_to_disk(file)

        if task_type == Task.UPLOAD_FILE:
            params = UploadInfoBlob(
                filepath=filepath,
                filename=filename,
                user_id=self.user.id,
                group_id=group_id,
                space_id=space_id,
                mimetype=mimetype,
            )
        elif task_type == Task.TRANSCRIPTION:
            params = Transcription(
                filepath=filepath,
                filename=filename,
                user_id=self.user.id,
                group_id=group_id,
                space_id=space_id,
                mimetype=mimetype,
            )

        # Set name of the job to the filename being processed
        job = await self.job_service.queue_job(task_type, name=filename, task_params=params)

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
