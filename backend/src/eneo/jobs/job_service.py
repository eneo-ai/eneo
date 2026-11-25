from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.transaction_callbacks import after_outer_transaction
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import (
    KNOWLEDGE_TASKS,
    Job,
    JobFailureCode,
    JobInDb,
    JobUpdate,
    Task,
)
from eneo.jobs.job_repo import ACTIVE_JOB_STATUSES, JobRepository
from eneo.jobs.job_staging import job_staging_path
from eneo.jobs.task_models import (
    AppDispatchEnvelope,
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


async def _enqueue_committed_job(task: Task, job_id: UUID, params: TaskParams) -> None:
    try:
        await job_manager.enqueue(task, job_id, params)
    except Exception:
        logger.exception(
            "Queue did not confirm job dispatch",
            extra={"job_id": str(job_id), "task": task.value},
        )


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
        self,
        task: Task,
        *,
        name: str,
        task_params: TaskParams,
        enqueue: bool = True,
        after_commit: bool = False,
        dispatch_envelope: AppDispatchEnvelope | None = None,
    ) -> JobInDb:
        """Add a QUEUED job row and hand the job to the worker.

        ``after_commit`` hands it over only once the surrounding transaction
        has committed: a worker that picked the job up earlier would not see
        the row, and a job that finished before the commit would be left
        QUEUED until the stale-job reaper fails it. A rolled-back transaction
        never dispatches. Sessions that are not ``AsyncSession`` (tests with
        fakes) dispatch immediately.
        """
        if task in KNOWLEDGE_TASKS:
            raise ValueError(f"Knowledge task {task.value} requires durable dispatch")
        job = Job(task=task, name=name, status=Status.QUEUED, user_id=self.user.id)
        if dispatch_envelope is None:
            job_in_db = await self.job_repo.add_job(job=job)
        else:
            if task != Task.RUN_APP or not enqueue or not after_commit:
                raise ValueError("App dispatch requires a post-commit app submission")
            job_in_db = await self.job_repo.add_durable_job(
                job, job_id=uuid4(), dispatch_envelope=dispatch_envelope
            )

        if not enqueue:
            return job_in_db
        if after_commit:
            await self.dispatch_after_commit(task, job_in_db.id, task_params)
        else:
            await job_manager.enqueue(task, job_in_db.id, task_params)
        return job_in_db

    async def dispatch_after_commit(
        self, task: Task, job_id: UUID, task_params: TaskParams
    ) -> None:
        """Hand a job queued with ``enqueue=False`` to the worker once the
        surrounding transaction has committed; never after a rollback.

        Must be called outside any savepoint. Sessions that are not
        ``AsyncSession`` (tests with fakes) dispatch immediately.
        """
        session = cast(object, self.job_repo.delegate.session)
        if not isinstance(session, AsyncSession):
            await job_manager.enqueue(task, job_id, task_params)
            return

        after_outer_transaction(
            session.sync_session,
            on_commit=lambda: _enqueue_committed_job(task, job_id, task_params),
        )

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
        job_in_db = await self.job_repo.add_durable_job(
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

    async def fail_job(
        self,
        job_id: UUID,
        *,
        failure_code: JobFailureCode,
        only_if_queued: bool = False,
    ):
        """Fail an active job. Store only the code since an error can quote
        the job's input. Use only_if_queued when the caller cannot confirm that
        it owns an in-progress job."""
        job_update = JobUpdate(
            status=Status.FAILED,
            finished_at=datetime.now(timezone.utc),
            result_location=None,
            failure_code=failure_code,
        )
        return await self.job_repo.update_job(
            job_id,
            job_update,
            from_statuses=(Status.QUEUED,) if only_if_queued else ACTIVE_JOB_STATUSES,
        )

    async def get_running_jobs(self):
        return await self.job_repo.get_running_jobs(self.user.id)

    async def get_job(self, job_id: UUID):
        job = await self.job_repo.get_job(job_id)

        if job is None or job.user_id != self.user.id:
            raise NotFoundException()

        return job
