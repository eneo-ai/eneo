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
from eneo.jobs.job_models import JobFailureCode, Task
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


def _recovery_page():
    return (
        sa.select(Jobs)
        .where(Jobs.task == Task.RUN_APP, Jobs.status.in_((_QUEUED, _RUNNING)))
        .order_by(Jobs.updated_at, Jobs.id)
        .limit(APP_RUN_RECOVERY_BATCH)
        .with_for_update(skip_locked=True)
    )


def interrupted_app_jobs(now: datetime):
    deadline = now - APP_RUN_QUEUE_TIMEOUT
    return _recovery_page().where(
        sa.or_(
            sa.and_(
                Jobs.status == _RUNNING, Jobs.updated_at < now - APP_RUN_RECOVERY_GRACE
            ),
            sa.and_(
                Jobs.status == _QUEUED,
                sa.or_(
                    sa.and_(
                        Jobs.dispatch_envelope.is_(None), Jobs.updated_at < deadline
                    ),
                    sa.and_(
                        Jobs.dispatch_envelope.is_not(None), Jobs.created_at <= deadline
                    ),
                ),
            ),
        )
    )


def retryable_app_submissions(now: datetime):
    return _recovery_page().where(
        Jobs.status == _QUEUED,
        Jobs.dispatch_envelope.is_not(None),
        Jobs.created_at > now - APP_RUN_QUEUE_TIMEOUT,
        Jobs.updated_at < now - APP_RUN_RECOVERY_GRACE,
    )


async def reconcile_app_runs(
    session: AsyncSession, *, now: datetime | None = None
) -> list[UUID]:
    now = now or datetime.now(timezone.utc)
    # Broker outages must not consume the capacity for reporting interrupted work.
    failures = [
        (job, JobFailureCode.PROCESSING_INTERRUPTED)
        for job in await session.scalars(interrupted_app_jobs(now))
    ]
    retry_jobs = list(await session.scalars(retryable_app_submissions(now)))
    runs = {}
    linked_files: dict[UUID, set[UUID]] = {}
    if retry_jobs:
        retry_ids = [job.id for job in retry_jobs]
        sources = await session.execute(
            sa.select(
                AppRuns.job_id, AppRuns.id, AppRuns.app_id, AppRuns.user_id
            ).where(AppRuns.job_id.in_(retry_ids))
        )
        runs = {row.job_id: row for row in sources}
        links = await session.execute(
            sa.select(AppRunsFiles.app_run_id, AppRunsFiles.file_id).where(
                AppRunsFiles.app_run_id.in_([run.id for run in runs.values()])
            )
        )
        for run_id, file_id in links:
            linked_files.setdefault(run_id, set()).add(file_id)

    broker_unavailable = False
    for job in retry_jobs:
        try:
            envelope = AppDispatchEnvelope.model_validate(job.dispatch_envelope)
            run = runs.get(job.id)
            if (
                run is None
                or run.user_id != job.user_id
                or set(envelope.file_ids) != linked_files.get(run.id, set())
            ):
                raise ValueError("App run inputs no longer match the submission")
            params = AppRunParams(
                id=run.id,
                app_id=run.app_id,
                user_id=job.user_id,
                file_ids=envelope.file_ids,
                text=None,
            )
        except ValueError:
            failures.append((job, JobFailureCode.INVALID_JOB_PAYLOAD))
            continue

        if broker_unavailable:
            continue
        job.updated_at = now
        job.dispatch_attempted_at = now
        try:
            async with asyncio.timeout(get_settings().redis_conn_timeout):
                await job_manager.redispatch_app(job.id, params)
        except Exception as exc:
            broker_unavailable = True
            logger.warning(
                "App redispatch unavailable",
                extra={"job_id": str(job.id), "error_type": type(exc).__name__},
            )

    failed: list[UUID] = []
    for job, code in failures:
        job.status = Status.FAILED
        job.failure_code = code
        job.finished_at = now
        job.result_location = None
        job.dispatch_envelope = None
        failed.append(job.id)

    await session.flush()
    await JobRepository(session).announce(*failed)
    return failed
