from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from arq.jobs import Job as ArqJob
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_models import JobFailureCode, Task
from eneo.jobs.task_models import TaskParams, validate_dispatch_envelope
from eneo.main.logging import get_logger
from eneo.main.models import Status

logger = get_logger(__name__)

DISPATCH_PAGE_SIZE = 50
DISPATCH_STALE_AFTER = timedelta(minutes=5)
# Prepared plans must see the fixed predicate used by the partial index.
_QUEUED_SQL = sa.literal_column("'queued'", type_=sa.String())
_DURABLE_TASKS_SQL = (
    sa.literal_column("'upload_info_blob'", type_=sa.String()),
    sa.literal_column("'transcription'", type_=sa.String()),
)
Enqueue = Callable[[Task, UUID, TaskParams], Awaitable[ArqJob | None]]


@dataclass(frozen=True)
class RedispatchResult:
    claimed: int
    enqueued: int
    failed: int


def stale_dispatch_statement(
    attempted_at: datetime,
) -> sa.Select[tuple[Jobs]]:
    stale_before = attempted_at - DISPATCH_STALE_AFTER
    return (
        sa.select(Jobs)
        .where(Jobs.status == _QUEUED_SQL)
        .where(Jobs.dispatch_envelope.is_not(None))
        .where(Jobs.task.in_(_DURABLE_TASKS_SQL))
        .where(Jobs.created_at <= stale_before)
        .where(
            sa.or_(
                Jobs.dispatch_attempted_at.is_(None),
                Jobs.dispatch_attempted_at <= stale_before,
            )
        )
        .order_by(Jobs.dispatch_attempted_at.asc().nullsfirst(), Jobs.id.asc())
        .limit(DISPATCH_PAGE_SIZE)
        .with_for_update(skip_locked=True)
    )


async def redispatch_stale_jobs(
    session: AsyncSession,
    *,
    enqueue: Enqueue,
    now: datetime | None = None,
) -> RedispatchResult:
    attempted_at = now or datetime.now(timezone.utc)
    statement = stale_dispatch_statement(attempted_at)
    jobs = list((await session.scalars(statement)).all())
    for job in jobs:
        job.dispatch_attempted_at = attempted_at
    await session.flush()

    enqueued = 0
    failed = 0
    for job in jobs:
        try:
            envelope = validate_dispatch_envelope(job.dispatch_envelope)
            task = Task(job.task)
            if envelope.task != task:
                raise ValueError("task does not match the persisted job")
            if envelope.params.user_id != job.user_id:
                raise ValueError("user does not match the persisted job")
        except (ValidationError, ValueError) as exc:
            reason = f"Invalid dispatch envelope: {exc}"
            job.status = Status.FAILED.value
            job.finished_at = attempted_at
            job.result_location = None
            job.failure_code = JobFailureCode.INVALID_JOB_PAYLOAD.value
            failed += 1
            logger.warning(
                "Durable job dispatch envelope is invalid",
                extra={
                    "job_id": str(job.id),
                    "task": job.task,
                    "failure_code": JobFailureCode.INVALID_JOB_PAYLOAD.value,
                    "reason": reason,
                },
            )
            continue

        result = await enqueue(task, job.id, envelope.params)
        if result is not None:
            enqueued += 1

    await session.flush()
    return RedispatchResult(claimed=len(jobs), enqueued=enqueued, failed=failed)
