from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa

from eneo.database.affected_rows import affected_row_count
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import Job, JobInDb, JobUpdate
from eneo.jobs.task_models import DispatchEnvelope

KNOWLEDGE_REAPER_PAGE_SIZE = 50
KNOWLEDGE_JOB_STALE_AFTER = timedelta(minutes=5)
KNOWLEDGE_REAPER_FAILURE_REASON = "Knowledge processing heartbeat expired"
_IN_PROGRESS_SQL = sa.literal_column("'in progress'", type_=sa.String())
_KNOWLEDGE_TASKS_SQL = (
    sa.literal_column("'upload_info_blob'", type_=sa.String()),
    sa.literal_column("'transcription'", type_=sa.String()),
)


def stale_in_progress_jobs_statement(stale_before: datetime):
    candidates = (
        sa.select(Jobs.id)
        .where(Jobs.status == _IN_PROGRESS_SQL)
        .where(Jobs.task.in_(_KNOWLEDGE_TASKS_SQL))
        .where(Jobs.updated_at < stale_before)
        .order_by(Jobs.updated_at.asc(), Jobs.id.asc())
        .limit(KNOWLEDGE_REAPER_PAGE_SIZE)
        .with_for_update(skip_locked=True)
        .cte("stale_knowledge_jobs")
    )
    return (
        sa.update(Jobs)
        .where(Jobs.id.in_(sa.select(candidates.c.id)))
        .where(Jobs.status == _IN_PROGRESS_SQL)
        .values(
            status="failed",
            result_location=KNOWLEDGE_REAPER_FAILURE_REASON,
            finished_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
        .returning(Jobs.id)
    )


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.delegate: BaseRepositoryDelegate[JobInDb] = BaseRepositoryDelegate(
            session,
            Jobs,
            JobInDb,
        )
        self._job_manager = job_manager

    async def add_job(self, job: Job):
        return await self.delegate.add(job)

    async def add_durable_knowledge_job(
        self,
        job: Job,
        *,
        job_id: UUID,
        dispatch_envelope: DispatchEnvelope,
    ) -> JobInDb:
        return await self.delegate.add(
            job,
            id=job_id,
            dispatch_envelope=dispatch_envelope.model_dump(mode="json"),
        )

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

    async def touch_job(self, id: UUID) -> bool:
        """Update an in-progress job's timestamp to signal 'still alive'.

        Used as a heartbeat during long-running tasks like crawls to prevent
        safe preemption from marking the job as stale.

        Args:
            id: Job UUID to touch
        """
        from eneo.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status == Status.IN_PROGRESS)
            .values(updated_at=sa.func.now())
        )
        result = await self.delegate.session.execute(stmt)
        return affected_row_count(result) > 0

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
        from eneo.main.models import Status

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
        return affected_row_count(result) > 0

    async def mark_job_completed(self, id: UUID, result_location: str) -> bool:
        from eneo.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status == Status.IN_PROGRESS)
            .values(
                status=Status.COMPLETE,
                result_location=result_location,
                finished_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        result = await self.delegate.session.execute(stmt)
        return affected_row_count(result) > 0

    async def mark_job_failed_if_running(
        self,
        id: UUID,
        error_message: str | None,
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
        from eneo.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status.in_([Status.IN_PROGRESS, Status.QUEUED]))
            .values(
                status=Status.FAILED,
                result_location=error_message,
                finished_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        result = await self.delegate.session.execute(stmt)
        return affected_row_count(result)

    async def mark_stale_jobs_failed(
        self,
        tasks: list[str],
        stale_before: datetime,
    ) -> list[UUID]:
        """Mark long-stuck QUEUED/IN_PROGRESS jobs as FAILED.

        A hard crash mid-task leaves a stuck Job row. Both states must be reaped:
        - IN_PROGRESS if the task durably committed that status, and
        - QUEUED because a task that runs its whole body in one transaction (e.g.
          SharePoint sync) has its IN_PROGRESS write rolled back on a hard crash,
          so the row reverts to its last committed state, QUEUED.
        Reaps rows for the given task types whose updated_at is older than
        ``stale_before`` (the threshold must exceed the longest legitimate run/queue
        wait so live or merely-slow jobs are never killed).

        Returns the ids of the jobs that were failed.
        """
        from eneo.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.task.in_(tasks))
            .where(Jobs.status.in_([Status.IN_PROGRESS.value, Status.QUEUED.value]))
            .where(Jobs.updated_at < stale_before)
            .values(
                status=Status.FAILED.value,
                finished_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
            .returning(Jobs.id)
        )
        result = await self.delegate.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def mark_stale_in_progress_jobs_failed(
        self,
        stale_before: datetime,
    ) -> list[UUID]:
        result = await self.delegate.session.execute(
            stale_in_progress_jobs_statement(stale_before)
        )
        return [row[0] for row in result.all()]

    async def get_running_jobs(self, user_id: UUID):
        one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)
        twenty_four_hours_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        five_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)

        stmt = (
            sa.select(Jobs)
            .where(Jobs.user_id == user_id)
            .where(Jobs.created_at >= one_week_ago)
            .where(
                # Include running, queued, recently failed, OR recently completed jobs
                sa.or_(
                    Jobs.status.in_(["in progress", "queued"]),
                    sa.and_(
                        Jobs.status == "failed",
                        Jobs.finished_at >= twenty_four_hours_ago,
                    ),
                    sa.and_(
                        Jobs.status == "complete", Jobs.finished_at >= five_minutes_ago
                    ),
                )
            )
            .order_by(Jobs.created_at)
        )

        jobs_db = await self.delegate.get_models_from_query(stmt)
        return jobs_db
