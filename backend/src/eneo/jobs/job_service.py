import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import event

from eneo.jobs.durable_dispatch import build_knowledge_dispatch_params
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Job, JobInDb, JobUpdate, Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.job_staging import job_staging_path
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

    async def queue_durable_knowledge_job(
        self,
        task: Task,
        *,
        name: str,
        task_params: UploadInfoBlob | Transcription,
        job_id: UUID | None = None,
    ) -> JobInDb:
        session = self.job_repo.delegate.session.sync_session
        if session.in_nested_transaction():
            raise ValueError(
                "Durable knowledge jobs cannot be created in a nested transaction"
            )
        if task not in (Task.UPLOAD_FILE, Task.TRANSCRIPTION):
            raise ValueError(f"Task {task.value} does not support durable dispatch")
        if task_params.user_id != self.user.id:
            raise ValueError("Durable knowledge job user does not match service user")

        envelope = build_dispatch_envelope(task, task_params)
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        job_in_db = await self.job_repo.add_durable_knowledge_job(
            job,
            job_id=job_id or uuid4(),
            dispatch_envelope=envelope,
        )

        async def dispatch_after_commit() -> None:
            try:
                dispatch_params = build_knowledge_dispatch_params(
                    task_params, job_in_db.id
                )
                await job_manager.enqueue(task, job_in_db.id, dispatch_params)
            except Exception:
                logger.exception(
                    "Immediate durable job dispatch failed",
                    extra={"job_id": str(job_in_db.id), "task": task.value},
                )

        def cleanup_after_rollback() -> None:
            try:
                job_staging_path(job_in_db.id).unlink(missing_ok=True)
            except Exception:
                logger.exception(
                    "Durable job staging cleanup after rollback failed",
                    extra={"job_id": str(job_in_db.id), "task": task.value},
                )

        outer_committed = False
        active = True

        def after_commit(_session: object) -> None:
            nonlocal outer_committed
            if active and not session.in_nested_transaction():
                outer_committed = True

        def remove_listeners() -> None:
            if event.contains(session, "after_commit", after_commit):
                event.remove(session, "after_commit", after_commit)
            if event.contains(session, "after_transaction_end", after_transaction_end):
                event.remove(session, "after_transaction_end", after_transaction_end)

        def after_transaction_end(_session: object, transaction: object) -> None:
            nonlocal active
            if not active or getattr(transaction, "parent", None) is not None:
                return

            active = False
            loop = asyncio.get_running_loop()
            if outer_committed:
                loop.create_task(dispatch_after_commit())
            else:
                cleanup_after_rollback()
            loop.call_soon(remove_listeners)

        event.listen(session, "after_commit", after_commit)
        event.listen(session, "after_transaction_end", after_transaction_end)
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
