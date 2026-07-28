from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.job_table import Jobs
from eneo.jobs.job_models import Task
from eneo.jobs.task_models import TaskParams, validate_dispatch_envelope
from eneo.main.logging import get_logger
from eneo.main.models import Status

logger = get_logger(__name__)

DISPATCH_PAGE_SIZE = 50
DISPATCH_STALE_AFTER = timedelta(minutes=5)
_DURABLE_TASKS = (Task.UPLOAD_FILE.value, Task.TRANSCRIPTION.value)
Enqueue = Callable[[Task, UUID, TaskParams], Awaitable[object]]


@dataclass(frozen=True)
class RedispatchResult:
    claimed: int
    enqueued: int
    failed: int


async def redispatch_stale_jobs(
    session: AsyncSession,
    *,
    enqueue: Enqueue,
    now: datetime | None = None,
) -> RedispatchResult:
    attempted_at = now or datetime.now(timezone.utc)
    stale_before = attempted_at - DISPATCH_STALE_AFTER
    statement = (
        sa.select(Jobs)
        .where(Jobs.status == Status.QUEUED.value)
        .where(Jobs.dispatch_envelope.is_not(None))
        .where(Jobs.task.in_(_DURABLE_TASKS))
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
            job.result_location = reason[:512]
            failed += 1
            logger.warning(
                "Durable job dispatch envelope is invalid",
                extra={"job_id": str(job.id), "reason": reason},
            )
            continue

        result = await enqueue(task, job.id, envelope.params)
        if result is not None:
            enqueued += 1

    await session.flush()
    return RedispatchResult(claimed=len(jobs), enqueued=enqueued, failed=failed)
