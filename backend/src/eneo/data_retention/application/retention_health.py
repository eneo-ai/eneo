"""Read-only retention health for the composition root's explicit task list."""

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from eneo.data_retention.application.retention_registration import (
    RetentionTaskRegistration,
)
from eneo.data_retention.domain.retention import (
    RETENTION_STALE_AFTER,
    RetentionErrorCode,
    RetentionJobOutcome,
)
from eneo.data_retention.infrastructure.retention_job_run_repo import (
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
    stale: bool = False
    overdue: bool = False
    missing: bool = False
    stale_overdue: bool = False
    failed: bool = False
    latest_outcome: RetentionJobOutcome | None = None
    error_code: RetentionErrorCode | None = None
    # The blocked reasons the latest run recorded (`<step>.<reason>`).
    blocked_reasons: tuple[str, ...] = ()
    overdue_complete: bool | None = None


class RetentionHealth(BaseModel):
    status: RetentionHealthStatus
    tasks: tuple[RetentionTaskHealth, ...] = ()


async def load_retention_health(
    repository: RetentionJobRunRepository,
    tasks: Sequence[RetentionTaskRegistration],
    *,
    now: datetime,
) -> RetentionHealth:
    """Read a bounded number of indexed observations per configured task.

    The caller supplies database/time limits and handles failures. A missing
    first run is initializing while no registered task has run; once one has,
    the scheduled run reached every task, so a task without a row (its claim
    raised before writing one) is unknown, as is missing evidence after a run.
    A run that failed is degraded; one that was superseded or could not claim
    its task proves nothing about the due work, so it is unknown.
    """
    stale_before = now - RETENTION_STALE_AFTER
    observations: list[RetentionTaskHealth] = []
    # Read once, and only when a task has no row.
    any_ran: bool | None = None
    for task in tasks:
        if not task.enabled:
            observations.append(
                RetentionTaskHealth(
                    name=task.name,
                    status=RetentionHealthStatus.DEGRADED,
                    disabled=True,
                )
            )
            continue
        latest = await repository.latest(task.name)
        stale = await repository.is_stale(task.name, stale_before=stale_before)
        snapshot = (
            await repository.latest_overdue(task.name) if task.reports_overdue else None
        )
        missing = latest is None or (task.reports_overdue and snapshot is None)
        stale_overdue = snapshot is not None and snapshot.observed_at < stale_before
        overdue = snapshot is not None and snapshot.overdue.count > 0
        failed = latest is not None and latest.outcome is RetentionJobOutcome.FAILED
        if stale or overdue or failed:
            status = RetentionHealthStatus.DEGRADED
        elif latest is None:
            if any_ran is None:
                any_ran = await repository.has_any_run(
                    [registered.name for registered in tasks]
                )
            status = (
                RetentionHealthStatus.UNKNOWN
                if any_ran
                else RetentionHealthStatus.INITIALIZING
            )
        elif latest.outcome is RetentionJobOutcome.SUPERSEDED or (
            latest.outcome is RetentionJobOutcome.SKIPPED
            and latest.error_code is RetentionErrorCode.CLAIM_TIMEOUT
        ):
            status = RetentionHealthStatus.UNKNOWN
        elif task.reports_overdue and snapshot is None:
            status = (
                RetentionHealthStatus.UNKNOWN
                if await repository.has_finished(task.name)
                else RetentionHealthStatus.INITIALIZING
            )
        elif stale_overdue or (
            snapshot is not None
            and snapshot.overdue.count == 0
            and not snapshot.overdue.complete
        ):
            status = RetentionHealthStatus.UNKNOWN
        else:
            status = RetentionHealthStatus.HEALTHY
        observations.append(
            RetentionTaskHealth(
                name=task.name,
                status=status,
                disabled=False,
                stale=stale,
                overdue=overdue,
                missing=missing,
                stale_overdue=stale_overdue,
                failed=failed,
                latest_outcome=latest.outcome if latest is not None else None,
                error_code=latest.error_code if latest is not None else None,
                blocked_reasons=tuple(
                    sorted(key for key, value in latest.blocked.items() if value)
                )
                if latest is not None
                else (),
                overdue_complete=snapshot.overdue.complete
                if snapshot is not None
                else None,
            )
        )
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
