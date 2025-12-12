from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa

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
        await self.delegate.session.execute(stmt)

    async def mark_job_started(self, id: UUID) -> bool:
        """Atomically transition job from QUEUED to IN_PROGRESS.

        Uses Compare-and-Swap (CAS) pattern to prevent race conditions where:
        1. Safe Watchdog marks expired QUEUED job as FAILED
        2. Worker dequeues same job from ARQ (doesn't know DB changed)
        3. Worker would blindly set status to IN_PROGRESS, "resurrecting" the job

        This atomic check-and-update ensures the worker only starts the job if
        it's still in QUEUED state, preventing zombie job resurrection.

        Args:
            id: Job UUID to start

        Returns:
            True if job was successfully transitioned to IN_PROGRESS
            False if job status had already changed (e.g., to FAILED by watchdog)
        """
        from intric.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status == Status.QUEUED)  # KEY: Only if still QUEUED
            .values(
                status=Status.IN_PROGRESS,
                updated_at=sa.func.now(),
            )
        )
        result = await self.delegate.session.execute(stmt)
        return result.rowcount > 0

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
        from intric.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status.in_([Status.IN_PROGRESS, Status.QUEUED]))
            .values(
                status=Status.FAILED,
                updated_at=sa.func.now(),
            )
        )
        result = await self.delegate.session.execute(stmt)
        return result.rowcount

    async def get_running_jobs(self, user_id: UUID):
        one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)

        stmt = (
            sa.select(Jobs)
            .where(Jobs.user_id == user_id)
            .where(Jobs.created_at >= one_week_ago)
            .where(
                # Include running, queued, failed, OR recently completed jobs
                sa.or_(
                    Jobs.status.in_(["in progress", "queued", "failed"]),
                    sa.and_(
                        Jobs.status == "complete",
                        Jobs.finished_at >= five_minutes_ago
                    )
                )
            )
            .order_by(Jobs.created_at)
        )

        jobs_db = await self.delegate.get_models_from_query(stmt)
        return jobs_db
