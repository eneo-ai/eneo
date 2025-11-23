from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from arq.jobs import JobStatus

from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.job_table import Jobs
from intric.jobs.job_manager import job_manager
from intric.jobs.job_models import Job, JobInDb, JobUpdate


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
            session,
            Jobs,
            JobInDb,
        )
        self._job_manager = job_manager

    async def add_job(self, job: Job):
        return await self.delegate.add(job)

    async def update_job(self, id: UUID, job: JobUpdate):
        stmt = (
            sa.update(Jobs)
            .values(job.model_dump(exclude_unset=True))
            .where(Jobs.id == id)
            .returning(Jobs)
        )

        return await self.delegate.get_model_from_query(stmt)

    async def get_job(self, id: UUID):
        return await self.delegate.get_by(conditions={Jobs.id: id})

    async def touch_job(self, id: UUID) -> None:
        """Update job's updated_at timestamp to signal 'still alive'.

        Used as a heartbeat during long-running tasks like crawls to prevent
        safe preemption from marking the job as stale.

        Args:
            id: Job UUID to touch
        """
        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .values(updated_at=sa.func.now())
        )
        await self.delegate._session.execute(stmt)

    async def mark_job_failed_if_running(
        self, id: UUID, error_message: str
    ) -> int:
        """Atomically mark a job as FAILED only if it's currently IN_PROGRESS or QUEUED.

        Uses Compare-and-Swap pattern to prevent race conditions when multiple
        users try to preempt the same job simultaneously.

        Args:
            id: Job UUID to fail
            error_message: Error message to store

        Returns:
            Number of rows affected (1 if successful, 0 if job was already
            completed/failed or doesn't exist)
        """
        from intric.jobs.task_models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status.in_([Status.IN_PROGRESS, Status.QUEUED]))
            .values(
                status=Status.FAILED,
                result={"error": error_message},
                updated_at=sa.func.now(),
            )
        )
        result = await self.delegate._session.execute(stmt)
        return result.rowcount

    async def get_running_jobs(self, user_id: UUID):
        one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)

        stmt = (
            sa.select(Jobs)
            .where(Jobs.user_id == user_id)
            .where(Jobs.created_at >= one_week_ago)
            .order_by(Jobs.created_at)
        )

        jobs_db = await self.delegate.get_models_from_query(stmt)

        running_jobs = [
            job
            for job in jobs_db
            if await self._job_manager.get_job_status(job.id)
            not in [JobStatus.not_found, JobStatus.complete]
        ]

        return running_jobs
