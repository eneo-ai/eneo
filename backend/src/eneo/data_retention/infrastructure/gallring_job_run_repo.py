"""Job executions of registered gallring tasks; the running row is the task's lease."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.domain.gallring import (
    GALLRING_COMPLETED_OUTCOMES,
    GallringErrorCode,
    GallringJobOutcome,
    GallringKeyset,
    gallring_name,
)
from eneo.data_retention.infrastructure.gallring_sql import (
    deployment_audit_retention_days,
    deployment_tenant_id,
    uuid_in,
)
from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.gallring_tables import GallringJobRuns

_RUNNING = GallringJobOutcome.RUNNING.value


def _owned(job_run_id: UUID) -> tuple[sa.ColumnElement[bool], ...]:
    return (GallringJobRuns.id == job_run_id, GallringJobRuns.outcome == _RUNNING)


def _stored_cursors(cursors: Mapping[str, GallringKeyset]) -> dict[str, Any]:
    return {
        gallring_name(step): {
            "at": keyset.at.isoformat(),
            "id": str(keyset.id),
            **({"item": keyset.item} if keyset.item is not None else {}),
        }
        for step, keyset in cursors.items()
    }


def _read_cursors(stored: object) -> dict[str, GallringKeyset]:
    """The step cursors of a job row; an entry of any other shape is dropped,
    which restarts that step's pass (never a wrong position)."""
    cursors: dict[str, GallringKeyset] = {}
    if not isinstance(stored, dict):
        return cursors
    for step, value in cast(dict[object, object], stored).items():
        try:
            entry = cast(dict[str, Any], value)
            cursors[gallring_name(cast(str, step))] = GallringKeyset(
                at=datetime.fromisoformat(entry["at"]),
                id=UUID(entry["id"]),
                item=entry.get("item"),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return cursors


class GallringJobRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(self, *, task: str, stale_after_seconds: int) -> UUID | None:
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
            sa.update(GallringJobRuns)
            .where(
                GallringJobRuns.task == task,
                GallringJobRuns.outcome == _RUNNING,
                GallringJobRuns.heartbeat_at
                < now - sa.func.make_interval(0, 0, 0, 0, 0, 0, stale_after_seconds),
            )
            .values(
                outcome=GallringJobOutcome.SUPERSEDED.value,
                finished_at=now,
            )
        )
        latest_cursors = (
            sa.select(GallringJobRuns.cursors)
            .where(
                GallringJobRuns.task == task,
                GallringJobRuns.outcome != GallringJobOutcome.SKIPPED.value,
            )
            .order_by(GallringJobRuns.started_at.desc(), GallringJobRuns.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        return await self.session.scalar(
            pg_insert(GallringJobRuns)
            .values(
                task=task,
                outcome=_RUNNING,
                started_at=now,
                heartbeat_at=now,
                cursors=sa.func.coalesce(latest_cursors, sa.text("'{}'::jsonb")),
            )
            .on_conflict_do_nothing(
                index_elements=[GallringJobRuns.task],
                # A literal predicate: the partial index is inferred at plan time.
                index_where=sa.text("outcome = 'running'"),
            )
            .returning(GallringJobRuns.id)
        )

    async def record_skip(self, *, task: str, error_code: GallringErrorCode) -> UUID:
        """A finished execution row for a run the deployment setting suppressed."""
        now = sa.func.clock_timestamp()
        job_run_id = await self.session.scalar(
            sa.insert(GallringJobRuns)
            .values(
                task=task,
                outcome=GallringJobOutcome.SKIPPED.value,
                started_at=now,
                heartbeat_at=now,
                finished_at=now,
                error_code=error_code.value,
            )
            .returning(GallringJobRuns.id)
        )
        if job_run_id is None:
            raise RuntimeError("Gallring skip record did not return an id.")
        return job_run_id

    async def deployment_tenant_id(self) -> UUID | None:
        """The deployment's tenant, which holds deployment-level audit events.

        One tenant per deployment (docs/adr/single-tenant-assumption.md); a
        legacy deployment with several uses its first.
        """
        return await self.session.scalar(sa.select(deployment_tenant_id()))

    async def cursors(self, job_run_id: UUID) -> dict[str, GallringKeyset]:
        return _read_cursors(
            await self.session.scalar(
                sa.select(GallringJobRuns.cursors).where(
                    GallringJobRuns.id == job_run_id
                )
            )
        )

    async def renew(self, job_run_id: UUID) -> bool:
        """The ownership check every chunk runs first; its row lock lasts to commit."""
        renewed = await self.session.scalar(
            sa.update(GallringJobRuns)
            .where(*_owned(job_run_id))
            .values(heartbeat_at=sa.func.clock_timestamp())
            .returning(GallringJobRuns.id)
        )
        return renewed is not None

    async def record_progress(
        self,
        job_run_id: UUID,
        *,
        batch_count: int,
        counts: Mapping[str, int],
        blocked: Mapping[str, int],
        cursors: Mapping[str, GallringKeyset],
    ) -> None:
        await self.session.execute(
            sa.update(GallringJobRuns)
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
        outcome: GallringJobOutcome,
        error_code: GallringErrorCode | None,
    ) -> bool:
        """Set the final outcome unless the execution was superseded meanwhile."""
        if outcome == GallringJobOutcome.RUNNING:
            raise ValueError("A finished execution needs a final outcome.")
        finished = await self.session.scalar(
            sa.update(GallringJobRuns)
            .where(*_owned(job_run_id))
            .values(
                outcome=outcome.value,
                finished_at=sa.func.clock_timestamp(),
                error_code=error_code.value if error_code is not None else None,
            )
            .returning(GallringJobRuns.id)
        )
        return finished is not None

    async def last_completed_at(self, task: str) -> datetime | None:
        return await self.session.scalar(
            sa.select(GallringJobRuns.finished_at)
            .where(
                GallringJobRuns.task == task,
                GallringJobRuns.outcome.in_(
                    [outcome.value for outcome in GALLRING_COMPLETED_OUTCOMES]
                ),
            )
            .order_by(GallringJobRuns.finished_at.desc())
            .limit(1)
        )

    async def first_started_at(self, task: str) -> datetime | None:
        return await self.session.scalar(
            sa.select(sa.func.min(GallringJobRuns.started_at)).where(
                GallringJobRuns.task == task
            )
        )

    async def prune_after_audit_retention(self, *, limit: int) -> int:
        """Delete finished executions older than the deployment's audit retention."""
        cutoff = sa.func.now() - sa.func.make_interval(
            0, 0, 0, deployment_audit_retention_days()
        )
        ids = list(
            await self.session.scalars(
                sa.select(GallringJobRuns.id)
                .where(GallringJobRuns.finished_at < cutoff)
                .order_by(GallringJobRuns.finished_at)
                .limit(limit)
            )
        )
        if not ids:
            return 0
        result = await self.session.execute(
            sa.delete(GallringJobRuns).where(uuid_in(GallringJobRuns.id, ids))
        )
        return affected_row_count(result)
