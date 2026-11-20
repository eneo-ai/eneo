"""Recover committed submissions from their job row and the owning app run."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.apps.app_runs.api.app_run_models import AppRunParams
from eneo.database.tables.app_table import AppRuns, AppRunsFiles
from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_manager import job_manager
from eneo.jobs.job_models import JobFailureCode, JobUpdate, Task
from eneo.jobs.job_repo import JobRepository
from eneo.jobs.task_models import AppDispatchEnvelope
from eneo.main.config import get_settings
from eneo.main.logging import get_logger
from eneo.main.models import Status

logger = get_logger(__name__)
APP_RUN_QUEUE_TIMEOUT = timedelta(hours=2)
APP_RUN_RECOVERY_GRACE = timedelta(minutes=5)
APP_RUN_RECOVERY_BATCH = 50
# PostgreSQL must be able to match the active-job partial index in a prepared plan.
_QUEUED = sa.literal_column("'queued'", type_=sa.String())
_RUNNING = sa.literal_column("'in progress'", type_=sa.String())


async def claim_app_job(repo: JobRepository, job_id: UUID) -> bool:
    return await repo.mark_job_started(job_id, durable_queue_age=APP_RUN_QUEUE_TIMEOUT)


def _recovery_page(limit: int):
    return (
        sa.select(Jobs)
        .where(Jobs.task == Task.RUN_APP, Jobs.status.in_((_QUEUED, _RUNNING)))
        .order_by(Jobs.updated_at, Jobs.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def interrupted_app_jobs(now: datetime):
    deadline = now - APP_RUN_QUEUE_TIMEOUT
    return (
        _recovery_page(APP_RUN_RECOVERY_BATCH)
        .with_only_columns(Jobs.id)
        .where(
            sa.or_(
                sa.and_(
                    Jobs.status == _RUNNING,
                    Jobs.updated_at < now - APP_RUN_RECOVERY_GRACE,
                ),
                sa.and_(
                    Jobs.status == _QUEUED,
                    sa.or_(
                        sa.and_(
                            Jobs.dispatch_envelope.is_(None), Jobs.updated_at < deadline
                        ),
                        sa.and_(
                            Jobs.dispatch_envelope.is_not(None),
                            Jobs.created_at <= deadline,
                        ),
                    ),
                ),
            )
        )
    )


def next_retryable_app_submission(now: datetime):
    return _recovery_page(1).where(
        Jobs.status == _QUEUED,
        Jobs.dispatch_envelope.is_not(None),
        Jobs.created_at > now - APP_RUN_QUEUE_TIMEOUT,
        Jobs.updated_at < now - APP_RUN_RECOVERY_GRACE,
    )


async def _fail_locked_job(
    repo: JobRepository, job_id: UUID, code: JobFailureCode, now: datetime
) -> None:
    await repo.update_job(
        job_id,
        JobUpdate(
            status=Status.FAILED,
            failure_code=code,
            finished_at=now,
            result_location=None,
        ),
    )


async def fail_interrupted_app_runs(
    session: AsyncSession, *, now: datetime | None = None
) -> list[UUID]:
    now = now or datetime.now(timezone.utc)
    async with session.begin():
        ids = list(await session.scalars(interrupted_app_jobs(now)))
        repo = JobRepository(session)
        for job_id in ids:
            await _fail_locked_job(
                repo, job_id, JobFailureCode.PROCESSING_INTERRUPTED, now
            )
        return ids


async def _submission_params(session: AsyncSession, job: Jobs) -> AppRunParams:
    envelope = AppDispatchEnvelope.model_validate(job.dispatch_envelope)
    rows = (
        await session.execute(
            sa.select(AppRuns.id, AppRuns.app_id, AppRuns.user_id, AppRunsFiles.file_id)
            .outerjoin(AppRunsFiles, AppRunsFiles.app_run_id == AppRuns.id)
            .where(AppRuns.job_id == job.id)
        )
    ).all()
    if (
        len({row.id for row in rows}) != 1
        or rows[0].user_id != job.user_id
        or {row.file_id for row in rows if row.file_id is not None}
        != set(envelope.file_ids)
    ):
        raise ValueError("App run inputs no longer match the submission")
    return AppRunParams(
        id=rows[0].id,
        app_id=rows[0].app_id,
        user_id=job.user_id,
        file_ids=envelope.file_ids,
        text=None,
    )


async def retry_app_submissions(
    session: AsyncSession, *, now: datetime | None = None
) -> list[UUID]:
    failed: list[UUID] = []
    for _ in range(APP_RUN_RECOVERY_BATCH):
        # Redis needs the ownership proof for this ID only. The next job remains
        # claimable while this transaction is waiting for its own broker reply.
        async with session.begin():
            attempted_at = now or datetime.now(timezone.utc)
            job = await session.scalar(next_retryable_app_submission(attempted_at))
            if job is None:
                break
            try:
                params = await _submission_params(session, job)
            except ValueError:
                await _fail_locked_job(
                    JobRepository(session),
                    job.id,
                    JobFailureCode.INVALID_JOB_PAYLOAD,
                    attempted_at,
                )
                failed.append(job.id)
                continue
            job.updated_at = attempted_at
            job.dispatch_attempted_at = attempted_at
            try:
                async with asyncio.timeout(get_settings().redis_conn_timeout):
                    await job_manager.redispatch_app(job.id, params)
            except Exception as exc:
                logger.warning(
                    "App redispatch unavailable",
                    extra={"job_id": str(job.id), "error_type": type(exc).__name__},
                )
                break
    return failed
