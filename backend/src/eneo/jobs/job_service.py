from datetime import datetime, timezone
from uuid import UUID, uuid4

from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import KNOWLEDGE_TASKS, Job, JobInDb, JobUpdate, Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import (
    DurableTaskParams,
    TaskParams,
    build_dispatch_envelope,
)
from eneo.main.exceptions import NotFoundException
from eneo.main.logging import get_logger
from eneo.main.models import Status
from eneo.users.user import UserInDB

logger = get_logger(__name__)

DURABLE_TASKS = (Task.UPLOAD_FILE, Task.TRANSCRIPTION, Task.RUN_FLOW)


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
        if task in KNOWLEDGE_TASKS:
            raise ValueError(f"Knowledge task {task.value} requires durable dispatch")
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        job_in_db = await self.job_repo.add_job(job=job)

        if enqueue:
            await job_manager.enqueue(task, job_in_db.id, task_params)

        return job_in_db

    async def queue_durable_job(
        self,
        task: Task,
        *,
        name: str,
        task_params: DurableTaskParams,
        job_id: UUID | None = None,
    ) -> JobInDb:
        """Persist a job with its dispatch envelope and enqueue it after commit.

        A durable job survives a lost enqueue: the redispatch cron re-reads
        the envelope. Knowledge jobs also keep a staging file that is removed
        on rollback; other tasks have nothing to clean.
        """
        session = self.job_repo.delegate.session.sync_session
        if session.in_nested_transaction():
            raise ValueError("Durable jobs cannot be created in a nested transaction")
        if task not in DURABLE_TASKS:
            raise ValueError(f"Task {task.value} does not support durable dispatch")
        if task_params.user_id != self.user.id:
            raise ValueError("Durable job user does not match service user")

        envelope = build_dispatch_envelope(task, task_params)
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        job_in_db = await self.job_repo.add_durable_knowledge_job(
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

        def cleanup_after_rollback() -> None:
            if task not in KNOWLEDGE_TASKS:
                return
            try:
                job_staging_path(job_in_db.id).unlink(missing_ok=True)
            except Exception:
                logger.exception(
                    "Durable job staging cleanup after rollback failed",
                    extra={"job_id": str(job_in_db.id), "task": task.value},
                )

        after_outer_transaction(
            session,
            on_commit=dispatch_after_commit,
            on_rollback=cleanup_after_rollback,
        )
        return job_in_db

    # The knowledge-only name the upload and transcription paths still use.
    queue_durable_knowledge_job = queue_durable_job

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
