from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa

from eneo.database.affected_rows import affected_row_count
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_events import publish_job_update_after_commit
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import (
    KNOWLEDGE_TASKS,
    Job,
    JobFailureCode,
    JobInDb,
    JobUpdate,
    Task,
)
from eneo.jobs.task_models import AppDispatchEnvelope, DispatchEnvelope
from eneo.main.models import Status

KNOWLEDGE_REAPER_PAGE_SIZE = 50
KNOWLEDGE_JOB_STALE_AFTER = timedelta(minutes=5)
_IN_PROGRESS_SQL = sa.literal_column("'in progress'", type_=sa.String())
ACTIVE_JOB_STATUSES = (Status.QUEUED, Status.IN_PROGRESS)
# Keep the fixed partial-index predicate visible in prepared plans.
_ACTIVE_JOB_STATUSES_SQL = tuple(
    sa.literal_column(f"'{status.value}'", type_=sa.String())
    for status in ACTIVE_JOB_STATUSES
)
_KNOWLEDGE_TASK_VALUES = tuple(task.value for task in KNOWLEDGE_TASKS)
_KNOWLEDGE_TASKS_SQL = tuple(
    sa.literal_column(f"'{task}'", type_=sa.String()) for task in _KNOWLEDGE_TASK_VALUES
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
            result_location=sa.null(),
            failure_code=JobFailureCode.PROCESSING_INTERRUPTED.value,
            finished_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
        .returning(Jobs.id, Jobs.task)
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

    async def add_durable_job(
        self,
        job: Job,
        *,
        job_id: UUID,
        dispatch_envelope: DispatchEnvelope | AppDispatchEnvelope,
    ) -> JobInDb:
        return await self.delegate.add(
            job,
            id=job_id,
            dispatch_envelope=dispatch_envelope.model_dump(mode="json"),
        )

    async def update_job(
        self,
        id: UUID,
        job: JobUpdate,
        *,
        from_statuses: tuple[Status, ...] = (),
    ):
        stmt = (
            sa.update(Jobs)
            .values(job.model_dump(exclude_unset=True))
            .where(Jobs.id == id)
            .returning(Jobs)
        )
        if job.status in (Status.COMPLETE, Status.FAILED):
            # Knowledge jobs retain their envelope until staging cleanup.
            stmt = stmt.values(
                dispatch_envelope=sa.case(
                    (Jobs.task == Task.RUN_APP, sa.null()), else_=Jobs.dispatch_envelope
                )
            )
        if from_statuses:
            stmt = stmt.where(Jobs.status.in_(from_statuses))

        updated = await self.delegate.get_model_from_query(stmt)
        if updated is not None:
            publish_job_update_after_commit(self.delegate.session, updated)
        return updated

    async def announce(self, *ids: UUID) -> None:
        """Publish the current state of these jobs once the transaction commits.

        Every status write goes through this repository, so this is the one
        place live updates (eneo.jobs.job_events) come from.
        """
        for id in ids:
            job = await self.get_job(id)
            if job is not None:
                publish_job_update_after_commit(self.delegate.session, job)

    async def get_job(self, id: UUID):
        return await self.delegate.get_by(conditions={Jobs.id: id})

    async def touch_job(self, id: UUID) -> bool:
        """Update an in-progress job's timestamp to signal 'still alive'.

        Upload processing uses this as a heartbeat and stops if the job has
        already become terminal. The update holds the row lock until commit,
        so app runs can keep maintenance from reaping a live worker.

        Args:
            id: Job UUID to touch
        """
        from eneo.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.status == Status.IN_PROGRESS)
            .values(updated_at=sa.func.clock_timestamp())
        )
        result = await self.delegate.session.execute(stmt)
        return affected_row_count(result) > 0

    async def mark_job_started(
        self, id: UUID, *, durable_queue_age: timedelta | None = None
    ) -> bool:
        """Atomically transition job from QUEUED to IN_PROGRESS.

        Uses Compare-and-Swap (CAS) to prevent a worker from resurrecting a job
        after another recovery path has already made it terminal.

        This atomic check-and-update ensures the worker only starts the job if
        it's still in QUEUED state, preventing zombie job resurrection.

        Args:
            id: Job UUID to start

        Returns:
            True if job was successfully transitioned to IN_PROGRESS
            False if job status had already changed
        """
        stmt = sa.update(Jobs).where(Jobs.id == id, Jobs.status == Status.QUEUED)
        if durable_queue_age is not None:
            stmt = stmt.where(
                sa.or_(
                    Jobs.dispatch_envelope.is_(None),
                    Jobs.created_at > sa.func.clock_timestamp() - durable_queue_age,
                )
            ).values(dispatch_envelope=sa.null(), updated_at=sa.func.clock_timestamp())
        started = await self.delegate.get_model_from_query(
            stmt.values(status=Status.IN_PROGRESS).returning(Jobs)
        )
        if started is not None:
            publish_job_update_after_commit(self.delegate.session, started)
        return started is not None

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
        completed = affected_row_count(result) > 0
        if completed:
            await self.announce(id)
        return completed

    async def mark_knowledge_job_failed_if_running(
        self,
        id: UUID,
        failure_code: JobFailureCode,
    ) -> int:
        """Fail an active knowledge job without persisting exception prose."""
        from eneo.main.models import Status

        stmt = (
            sa.update(Jobs)
            .where(Jobs.id == id)
            .where(Jobs.task.in_(_KNOWLEDGE_TASK_VALUES))
            .where(Jobs.status.in_([Status.IN_PROGRESS, Status.QUEUED]))
            .values(
                status=Status.FAILED,
                result_location=None,
                failure_code=failure_code.value,
                finished_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
        )
        result = await self.delegate.session.execute(stmt)
        failed = affected_row_count(result)
        if failed:
            await self.announce(id)
        return failed

    async def mark_stale_jobs_failed(
        self,
        tasks: list[str],
        stale_before: datetime,
        *,
        limit: int | None = None,
        failure_code: JobFailureCode | None = None,
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
        candidates = (
            sa.select(Jobs.id)
            .where(Jobs.task.in_(tasks))
            .where(Jobs.status.in_(_ACTIVE_JOB_STATUSES_SQL))
            .where(Jobs.updated_at < stale_before)
            .order_by(Jobs.updated_at, Jobs.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .cte("stale_jobs")
        )
        stmt = (
            sa.update(Jobs)
            .where(Jobs.id.in_(sa.select(candidates.c.id)))
            .where(Jobs.status.in_(_ACTIVE_JOB_STATUSES_SQL))
            .values(
                status=Status.FAILED.value,
                finished_at=sa.func.now(),
                updated_at=sa.func.now(),
            )
            .returning(Jobs)
        )
        if failure_code is not None:
            stmt = stmt.values(failure_code=failure_code.value, result_location=None)
        result = await self.delegate.session.execute(stmt)
        failed_jobs = result.scalars().all()
        for job in failed_jobs:
            publish_job_update_after_commit(
                self.delegate.session, JobInDb.model_validate(job)
            )
        return [job.id for job in failed_jobs]

    async def mark_stale_in_progress_jobs_failed(
        self,
        stale_before: datetime,
    ) -> list[tuple[UUID, str]]:
        result = await self.delegate.session.execute(
            stale_in_progress_jobs_statement(stale_before)
        )
        failed = [(row.id, row.task) for row in result.all()]
        await self.announce(*(id for id, _task in failed))
        return failed

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
