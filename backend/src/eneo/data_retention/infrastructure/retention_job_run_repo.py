"""Job executions of registered retention tasks; the running row is the task's lease."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypeGuard
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.retention import (
    RETENTION_COMPLETED_OUTCOMES,
    RetentionErrorCode,
    RetentionJobOutcome,
    RetentionKeyset,
    RetentionOverdue,
    retention_name,
)
from eneo.data_retention.infrastructure.retention_sql import (
    deployment_audit_retention_days,
    deployment_tenant_id,
    uuid_in,
)
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.retention_tables import RetentionJobRuns

logger = logging.getLogger(__name__)

_RUNNING = RetentionJobOutcome.RUNNING.value


def _owned(job_run_id: UUID) -> tuple[sa.ColumnElement[bool], ...]:
    return (RetentionJobRuns.id == job_run_id, RetentionJobRuns.outcome == _RUNNING)


def _stored_cursors(
    cursors: Mapping[str, RetentionKeyset],
) -> dict[str, dict[str, str]]:
    return {
        retention_name(step): {
            "at": keyset.at.isoformat(),
            "id": str(keyset.id),
            **({"group": str(keyset.group)} if keyset.group is not None else {}),
        }
        for step, keyset in cursors.items()
    }


def _object_map(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _read_cursor(value: object) -> RetentionKeyset | None:
    """One stored step cursor, or None when it has any other shape."""
    if not _object_map(value):
        return None
    at, identifier, group = value.get("at"), value.get("id"), value.get("group")
    if not isinstance(at, str) or not isinstance(identifier, str):
        return None
    if group is not None and not isinstance(group, str):
        return None
    try:
        return RetentionKeyset(
            at=datetime.fromisoformat(at),
            id=UUID(identifier),
            group=UUID(group) if group is not None else None,
        )
    except (TypeError, ValueError):
        return None


def _read_cursors(stored: object) -> dict[str, RetentionKeyset]:
    """The step cursors of a job row; an entry of any other shape is dropped,
    which restarts that step's pass (never a wrong position), and logged."""
    cursors: dict[str, RetentionKeyset] = {}
    if not _object_map(stored):
        return cursors
    for step, value in stored.items():
        try:
            name = retention_name(step) if isinstance(step, str) else None
        except ValueError:
            name = None
        keyset = _read_cursor(value)
        if name is not None and keyset is not None:
            cursors[name] = keyset
            continue
        # Only a valid step name is logged; the stored value may be anything.
        logger.warning(
            "Dropped a malformed retention cursor of step %s; the step restarts "
            "its pass.",
            name if name is not None else "<invalid name>",
        )
    return cursors


def _int_map(stored: object) -> dict[str, int]:
    """A job row's count map; entries of any other shape are dropped."""
    if not _object_map(stored):
        return {}
    return {
        key: value
        for key, value in stored.items()
        if isinstance(key, str) and isinstance(value, int) and value >= 0
    }


@dataclass(frozen=True, slots=True)
class RetentionOverdueSnapshot:
    observed_at: datetime
    overdue: RetentionOverdue


@dataclass(frozen=True, slots=True)
class RetentionJobRunRecord:
    outcome: RetentionJobOutcome
    blocked: dict[str, int]
    error_code: RetentionErrorCode | None
    # The last renewal; a running row that stopped renewing was abandoned.
    heartbeat_at: datetime


@dataclass(frozen=True, slots=True)
class RetentionJobPruneResult:
    examined: int
    deleted: int


class RetentionJobRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(self, *, task: str, lease_stale_seconds: int) -> UUID | None:
        """Start an execution, superseding a stale one; None means the claim is lost.

        Runs inside the caller's transaction. The supersession rechecks the running
        outcome and the stale heartbeat in its own WHERE (an execution that renewed
        meanwhile keeps its lease), and the partial unique index lets only one
        running row exist, so a concurrent claim inserts nothing. The caller rolls
        the transaction back on a lost claim, which also undoes the supersession.
        The new execution starts from the step cursors of the task's newest
        execution that ran (skipped ones never ran).
        """
        now = sa.func.clock_timestamp()
        await self.session.execute(
            sa.update(RetentionJobRuns)
            .where(
                RetentionJobRuns.task == task,
                RetentionJobRuns.outcome == _RUNNING,
                RetentionJobRuns.heartbeat_at
                < now - sa.func.make_interval(0, 0, 0, 0, 0, 0, lease_stale_seconds),
            )
            .values(
                outcome=RetentionJobOutcome.SUPERSEDED.value,
                finished_at=now,
            )
        )
        latest_cursors = (
            sa.select(RetentionJobRuns.cursors)
            .where(
                RetentionJobRuns.task == task,
                RetentionJobRuns.outcome != RetentionJobOutcome.SKIPPED.value,
            )
            .order_by(RetentionJobRuns.started_at.desc(), RetentionJobRuns.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        return await self.session.scalar(
            pg_insert(RetentionJobRuns)
            .values(
                task=task,
                outcome=_RUNNING,
                started_at=now,
                heartbeat_at=now,
                cursors=sa.func.coalesce(latest_cursors, sa.text("'{}'::jsonb")),
            )
            .on_conflict_do_nothing(
                index_elements=[RetentionJobRuns.task],
                # A literal predicate: the partial index is inferred at plan time.
                index_where=sa.text("outcome = 'running'"),
            )
            .returning(RetentionJobRuns.id)
        )

    async def record_skip(self, *, task: str, error_code: RetentionErrorCode) -> UUID:
        """A finished execution row for a run the deployment setting suppressed."""
        now = sa.func.clock_timestamp()
        job_run_id = await self.session.scalar(
            sa.insert(RetentionJobRuns)
            .values(
                task=task,
                outcome=RetentionJobOutcome.SKIPPED.value,
                started_at=now,
                heartbeat_at=now,
                finished_at=now,
                error_code=error_code.value,
            )
            .returning(RetentionJobRuns.id)
        )
        if job_run_id is None:
            raise RuntimeError("Retention skip record did not return an id.")
        return job_run_id

    async def deployment_tenant_id(self) -> UUID | None:
        """The deployment's tenant, which holds deployment-level audit events.

        One tenant per deployment (docs/adr/single-tenant-assumption.md); a
        legacy deployment with several uses its first.
        """
        return await self.session.scalar(sa.select(deployment_tenant_id()))

    async def cursors(self, job_run_id: UUID) -> dict[str, RetentionKeyset]:
        return _read_cursors(
            await self.session.scalar(
                sa.select(RetentionJobRuns.cursors).where(
                    RetentionJobRuns.id == job_run_id
                )
            )
        )

    async def renew(self, job_run_id: UUID) -> bool:
        """The ownership check every chunk runs first; its row lock lasts to commit."""
        renewed = await self.session.scalar(
            sa.update(RetentionJobRuns)
            .where(*_owned(job_run_id))
            .values(heartbeat_at=sa.func.clock_timestamp())
            .returning(RetentionJobRuns.id)
        )
        return renewed is not None

    async def record_progress(
        self,
        job_run_id: UUID,
        *,
        batch_count: int,
        counts: Mapping[str, int],
        blocked: Mapping[str, int],
        cursors: Mapping[str, RetentionKeyset],
    ) -> None:
        await self.session.execute(
            sa.update(RetentionJobRuns)
            .where(*_owned(job_run_id))
            .values(
                batch_count=batch_count,
                counts=dict(counts),
                blocked=dict(blocked),
                cursors=_stored_cursors(cursors),
            )
        )

    async def finish(
        self,
        job_run_id: UUID,
        *,
        outcome: RetentionJobOutcome,
        error_code: RetentionErrorCode | None,
    ) -> bool:
        """Set the final outcome unless the execution was superseded meanwhile."""
        if outcome == RetentionJobOutcome.RUNNING:
            raise ValueError("A finished execution needs a final outcome.")
        finished = await self.session.scalar(
            sa.update(RetentionJobRuns)
            .where(*_owned(job_run_id))
            .values(
                outcome=outcome.value,
                finished_at=sa.func.clock_timestamp(),
                error_code=error_code.value if error_code is not None else None,
            )
            .returning(RetentionJobRuns.id)
        )
        return finished is not None

    async def record_overdue(self, job_run_id: UUID, overdue: RetentionOverdue) -> bool:
        """The execution's overdue snapshot; False once it no longer owns the task."""
        recorded = await self.session.scalar(
            sa.update(RetentionJobRuns)
            .where(*_owned(job_run_id))
            .values(
                heartbeat_at=sa.func.clock_timestamp(),
                overdue_observed_at=sa.func.clock_timestamp(),
                overdue_count=overdue.count,
                overdue_complete=overdue.complete,
                overdue_oldest_due_at=overdue.oldest_due_at,
            )
            .returning(RetentionJobRuns.id)
        )
        return recorded is not None

    async def latest_overdue(self, task: str) -> RetentionOverdueSnapshot | None:
        """The task's newest overdue snapshot, whatever the execution's outcome."""
        row = (
            await self.session.execute(
                sa.select(
                    RetentionJobRuns.overdue_observed_at,
                    RetentionJobRuns.overdue_count,
                    RetentionJobRuns.overdue_complete,
                    RetentionJobRuns.overdue_oldest_due_at,
                )
                .where(
                    RetentionJobRuns.task == task,
                    RetentionJobRuns.overdue_observed_at.is_not(None),
                )
                .order_by(RetentionJobRuns.overdue_observed_at.desc())
                .limit(1)
            )
        ).one_or_none()
        if row is None or row[0] is None or row[1] is None or row[2] is None:
            return None
        return RetentionOverdueSnapshot(
            observed_at=row[0],
            overdue=RetentionOverdue(
                count=row[1], complete=row[2], oldest_due_at=row[3]
            ),
        )

    async def latest(self, task: str) -> RetentionJobRunRecord | None:
        """The task's newest execution (any outcome): what health reports of it."""
        row = await self.session.scalar(
            sa.select(RetentionJobRuns)
            .where(RetentionJobRuns.task == task)
            .order_by(RetentionJobRuns.started_at.desc(), RetentionJobRuns.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return RetentionJobRunRecord(
            outcome=RetentionJobOutcome(row.outcome),
            blocked=_int_map(row.blocked),
            error_code=(
                RetentionErrorCode(row.error_code)
                if row.error_code is not None
                else None
            ),
            heartbeat_at=row.heartbeat_at,
        )

    async def has_any_run(self, tasks: Sequence[str]) -> bool:
        """Whether any of `tasks` has an execution row of any outcome."""
        return (
            await self.session.scalar(
                sa.select(RetentionJobRuns.id)
                .where(RetentionJobRuns.task.in_(tasks))
                .limit(1)
            )
        ) is not None

    async def has_finished(self, task: str) -> bool:
        return (
            await self.session.scalar(
                sa.select(RetentionJobRuns.id)
                .where(
                    RetentionJobRuns.task == task,
                    RetentionJobRuns.finished_at.is_not(None),
                    RetentionJobRuns.outcome != RetentionJobOutcome.SKIPPED.value,
                )
                .limit(1)
            )
        ) is not None

    async def last_completed_at(self, task: str) -> datetime | None:
        return await self.session.scalar(
            sa.select(RetentionJobRuns.finished_at)
            .where(
                RetentionJobRuns.task == task,
                RetentionJobRuns.outcome.in_(
                    [outcome.value for outcome in RETENTION_COMPLETED_OUTCOMES]
                ),
            )
            .order_by(RetentionJobRuns.finished_at.desc())
            .limit(1)
        )

    async def is_stale(self, task: str, *, stale_before: datetime) -> bool:
        """No completion (never completed: no first start) since `stale_before`;
        a task that never ran is not stale."""
        anchor = await self.last_completed_at(task)
        if anchor is None:
            anchor = await self.first_started_at(task)
        return anchor is not None and anchor < stale_before

    async def first_started_at(self, task: str) -> datetime | None:
        return await self.session.scalar(
            sa.select(sa.func.min(RetentionJobRuns.started_at)).where(
                RetentionJobRuns.task == task
            )
        )

    async def prune_after_audit_retention(
        self, *, limit: int
    ) -> RetentionJobPruneResult:
        """Lock and prune at most `limit` expired, finished executions.

        The caller audits and charges discovery plus deletion in its transaction.
        Running executions remain leases regardless of their start or heartbeat age.
        """
        if limit <= 0:
            raise ValueError("A job-history prune limit must be positive.")
        cutoff = sa.func.now() - sa.func.make_interval(
            0, 0, 0, deployment_audit_retention_days()
        )
        expired = (
            RetentionJobRuns.finished_at < cutoff,
            RetentionJobRuns.outcome != _RUNNING,
        )
        ids = list(
            await self.session.scalars(
                sa.select(RetentionJobRuns.id)
                .where(*expired)
                .order_by(RetentionJobRuns.finished_at, RetentionJobRuns.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        if not ids:
            return RetentionJobPruneResult(examined=0, deleted=0)
        result = await self.session.execute(
            sa.delete(RetentionJobRuns).where(
                uuid_in(RetentionJobRuns.id, ids), *expired
            )
        )
        return RetentionJobPruneResult(
            examined=len(ids), deleted=affected_row_count(result)
        )
