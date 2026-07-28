import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import event

from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Job, JobInDb, JobUpdate, Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.task_models import (
    TaskParams,
    Transcription,
    UploadInfoBlob,
    build_dispatch_envelope,
)
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.main.models import Status
from eneo.users.user import UserInDB

logger = get_logger(__name__)


class JobService:
    def __init__(
        self,
        user: UserInDB,
        job_repo: JobRepository,
    ) -> None:
        super().__init__()
        self.user = user
        self.job_repo = job_repo

    async def queue_job(
        self, task: Task, *, name: str, task_params: TaskParams, enqueue: bool = True
    ) -> JobInDb:
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        job_in_db = await self.job_repo.add_job(job=job)

        if enqueue:
            await job_manager.enqueue(task, job_in_db.id, task_params)

        return job_in_db

    async def queue_restart_safe_job(
        self,
        task: Task,
        *,
        name: str,
        task_params: UploadInfoBlob | Transcription,
        job_id: UUID | None = None,
    ) -> JobInDb:
        if task not in (Task.UPLOAD_FILE, Task.TRANSCRIPTION):
            raise ValueError(f"Task {task.value} does not support durable dispatch")

        envelope = build_dispatch_envelope(task, task_params)
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        job_in_db = await self.job_repo.add_restart_safe_job(
            job,
            job_id=job_id or uuid4(),
            dispatch_envelope=envelope,
        )

        async def dispatch_after_commit() -> None:
            try:
                await job_manager.enqueue(task, job_in_db.id, task_params)
            except Exception:
                logger.exception(
                    "Immediate durable job dispatch failed",
                    extra={"job_id": str(job_in_db.id), "task": task.value},
                )

        def schedule_dispatch(_session: object) -> None:
            asyncio.get_running_loop().create_task(dispatch_after_commit())

        event.listen(
            self.job_repo.delegate.session.sync_session,
            "after_commit",
            schedule_dispatch,
            once=True,
        )
        return job_in_db

    async def set_status(self, job_id: UUID, status: Status):
        job_update = JobUpdate(status=status)

        return await self.job_repo.update_job(job_id, job_update)

    async def complete_job(self, job_id: UUID, result_location: str | None):
        job_update = JobUpdate(
            status=Status.COMPLETE,
            result_location=result_location,
            finished_at=datetime.now(timezone.utc),
        )

        return await self.job_repo.update_job(job_id, job_update)

    async def fail_job(self, job_id: UUID, error_message: str | None = None):
        job_update = JobUpdate(
            status=Status.FAILED,
            finished_at=datetime.now(timezone.utc),
            result_location=error_message,
        )

        return await self.job_repo.update_job(job_id, job_update)

    async def get_running_jobs(self):
        return await self.job_repo.get_running_jobs(self.user.id)

    async def get_job(self, job_id: UUID):
        job = await self.job_repo.get_job(job_id)

        if job is None or job.user_id != self.user.id:
            raise NotFoundException()

        return job
