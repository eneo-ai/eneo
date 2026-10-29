"""Read-only retention health for the composition root's explicit task list."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel

from eneo.data_retention.application.retention_registration import (
    RetentionTaskRegistration,
)
from eneo.data_retention.application.retention_runner import overdue_reporter
from eneo.data_retention.domain.retention import (
    RETENTION_STALE_AFTER,
    RetentionErrorCode,
    RetentionJobOutcome,
)
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRecord,
    RetentionJobRunRepository,
)


class RetentionHealthStatus(StrEnum):
    INITIALIZING = "initializing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class RetentionTaskHealth(BaseModel):
    """Status and typed reasons only: /api/healthz is unauthenticated, and the
    counts and times of each run are in the audit log and the job history."""

    name: str
    status: RetentionHealthStatus
    disabled: bool = False
    """The worker's latest execution was skipped because a deployment setting
    turns the task off (before any execution: the API process's setting).
    Status degraded: no due data is removed."""
    stale: bool = False
    """No execution completed (succeeded or partial) for two days."""
    overdue: bool = False
    """The latest overdue snapshot counts due data still stored past its
    deadline and the overdue window."""
    no_execution: bool = False
    """The task has no execution row at all."""
    no_overdue_snapshot: bool = False
    """The task reports overdue work and has executions, but none of them wrote
    an overdue snapshot (yet: the first execution is still running)."""
    overdue_snapshot_stale: bool = False
    """The newest overdue snapshot is older than two days."""
    abandoned: bool = False
    """The latest execution is still running but stopped renewing its lease
    (for example a crashed worker); status unknown until a later run takes over."""
    failed: bool = False
    """The latest execution failed."""
    latest_outcome: RetentionJobOutcome | None = None
    error_code: RetentionErrorCode | None = None
    blocked_reasons: tuple[str, ...] = ()
    """The blocked reasons the latest run recorded (`<step>.<reason>`)."""
    overdue_complete: bool | None = None
    """Whether the newest overdue snapshot counted all overdue data (False: the
    count is a lower bound)."""


class RetentionHealth(BaseModel):
    status: RetentionHealthStatus
    tasks: tuple[RetentionTaskHealth, ...] = ()


def _turned_off(latest: RetentionJobRunRecord | None, *, enabled: bool) -> bool:
    """The worker's latest decision; the API process's setting only before any
    execution, as the two processes may be configured apart."""
    if latest is None:
        return not enabled
    return (
        latest.outcome is RetentionJobOutcome.SKIPPED
        and latest.error_code is RetentionErrorCode.DISABLED_BY_DEPLOYMENT_SETTING
    )


async def load_retention_health(
    repository: RetentionJobRunRepository,
    tasks: Sequence[RetentionTaskRegistration],
    *,
    now: datetime,
    lease_stale_after: timedelta,
) -> RetentionHealth:
    """Read a bounded number of indexed observations per configured task.

    The caller supplies database/time limits and handles failures. A missing
    first run is initializing while no registered task has run; once one has,
    the scheduled run reached every task, so a task without a row (its claim
    raised before writing one) is unknown, as is missing evidence after a run.
    A run that failed is degraded; one that was superseded, abandoned or could
    not claim its task proves nothing about the due work, so it is unknown.
    A task turned off is degraded.
    """
    names = [registered.name for registered in tasks]
    # Read once, and only when a task has no row.
    any_ran: list[bool] = []

    async def other_task_ran() -> bool:
        if not any_ran:
            any_ran.append(await repository.has_any_run(names))
        return any_ran[0]

    observations = [
        await _task_health(
            repository,
            task,
            now=now,
            lease_stale_after=lease_stale_after,
            other_task_ran=other_task_ran,
        )
        for task in tasks
    ]
    statuses = {task.status for task in observations}
    status = next(
        (
            candidate
            for candidate in (
                RetentionHealthStatus.DEGRADED,
                RetentionHealthStatus.UNKNOWN,
                RetentionHealthStatus.INITIALIZING,
            )
            if candidate in statuses
        ),
        RetentionHealthStatus.HEALTHY,
    )
    return RetentionHealth(status=status, tasks=tuple(observations))


async def _task_health(
    repository: RetentionJobRunRepository,
    task: RetentionTaskRegistration,
    *,
    now: datetime,
    lease_stale_after: timedelta,
    other_task_ran: Callable[[], Awaitable[bool]],
) -> RetentionTaskHealth:
    latest = await repository.latest(task.name)
    latest_outcome = latest.outcome if latest is not None else None
    error_code = latest.error_code if latest is not None else None
    blocked_reasons = (
        tuple(sorted(key for key, value in latest.blocked.items() if value))
        if latest is not None
        else ()
    )
    if _turned_off(latest, enabled=task.enabled):
        return RetentionTaskHealth(
            name=task.name,
            status=RetentionHealthStatus.DEGRADED,
            disabled=True,
            no_execution=latest is None,
            latest_outcome=latest_outcome,
            error_code=error_code,
            blocked_reasons=blocked_reasons,
        )
    stale_before = now - RETENTION_STALE_AFTER
    reports_overdue = overdue_reporter(task.build(repository.session)) is not None
    stale = await repository.is_stale(task.name, stale_before=stale_before)
    snapshot = await repository.latest_overdue(task.name) if reports_overdue else None
    no_overdue_snapshot = latest is not None and reports_overdue and snapshot is None
    overdue_snapshot_stale = (
        snapshot is not None and snapshot.observed_at < stale_before
    )
    overdue = snapshot is not None and snapshot.overdue.count > 0
    failed = latest_outcome is RetentionJobOutcome.FAILED
    abandoned = (
        latest is not None
        and latest.outcome is RetentionJobOutcome.RUNNING
        and latest.heartbeat_at < now - lease_stale_after
    )
    if stale or overdue or failed:
        status = RetentionHealthStatus.DEGRADED
    elif latest is None:
        status = (
            RetentionHealthStatus.UNKNOWN
            if await other_task_ran()
            else RetentionHealthStatus.INITIALIZING
        )
    elif (
        abandoned
        or latest.outcome is RetentionJobOutcome.SUPERSEDED
        or error_code is RetentionErrorCode.CLAIM_TIMEOUT
    ):
        status = RetentionHealthStatus.UNKNOWN
    elif no_overdue_snapshot:
        status = (
            RetentionHealthStatus.UNKNOWN
            if await repository.has_finished(task.name)
            else RetentionHealthStatus.INITIALIZING
        )
    elif overdue_snapshot_stale or (
        snapshot is not None
        and snapshot.overdue.count == 0
        and not snapshot.overdue.complete
    ):
        status = RetentionHealthStatus.UNKNOWN
    else:
        status = RetentionHealthStatus.HEALTHY
    return RetentionTaskHealth(
        name=task.name,
        status=status,
        stale=stale,
        overdue=overdue,
        no_execution=latest is None,
        no_overdue_snapshot=no_overdue_snapshot,
        overdue_snapshot_stale=overdue_snapshot_stale,
        abandoned=abandoned,
        failed=failed,
        latest_outcome=latest_outcome,
        error_code=error_code,
        blocked_reasons=blocked_reasons,
        overdue_complete=snapshot.overdue.complete if snapshot is not None else None,
    )
