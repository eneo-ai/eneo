from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import FlowRetentionHolds, FlowRuns, Flows
from eneo.database.tables.tenant_table import Tenants
from eneo.flows.domain.flow_retention_hold import (
    FlowRetentionHold,
    FlowRetentionHoldPage,
    FlowRetentionHoldStatusFilter,
    flow_retention_hold_actor,
)
from eneo.flows.flow_retention_policy import resolve_flow_retention_policy
from eneo.main.exceptions import NotFoundException


def flow_retention_hold_is_active() -> sa.ColumnElement[bool]:
    """A hold counts until it is released or its end date passes (database clock)."""
    return sa.and_(
        FlowRetentionHolds.released_at.is_(None),
        sa.or_(
            FlowRetentionHolds.ends_at.is_(None),
            FlowRetentionHolds.ends_at > sa.func.now(),
        ),
    )


def flow_retention_hold_review_overdue() -> sa.ColumnElement[bool]:
    """Active, and its review date has passed. It stays active: review is a flag."""
    return sa.and_(
        flow_retention_hold_is_active(),
        FlowRetentionHolds.review_by <= sa.func.now(),
    )


def flow_run_held_predicate(
    *,
    run_id: sa.ColumnElement[UUID] | Any,
    flow_id: sa.ColumnElement[UUID] | Any,
) -> sa.Exists:
    """True while any active hold covers the run.

    The one owner of "held": the history purge (selection and recheck) and the
    debug-evidence redaction exclude runs for which this is true. A Flow hold
    covers every run of the Flow, also runs created after it; a run hold covers
    that run.
    """
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRetentionHolds)
        .where(flow_retention_hold_is_active())
        .where(
            sa.or_(
                sa.and_(
                    FlowRetentionHolds.flow_run_id.is_(None),
                    FlowRetentionHolds.flow_id == flow_id,
                ),
                FlowRetentionHolds.flow_run_id == run_id,
            )
        )
        .exists()
    )


# Data that belongs to no run: a typed NULL run never equals a run hold's run
# (IS NULL would match every Flow hold of every Flow).
_NO_RUN = sa.cast(sa.null(), PG_UUID(as_uuid=True))


def flow_runless_data_held_predicate(
    *, flow_id: sa.ColumnElement[UUID] | Any
) -> sa.Exists:
    """flow_run_held_predicate for data of the Flow that belongs to no run (an
    unused upload or live transcript, a gallring receipt): only a Flow hold
    covers it."""
    return flow_run_held_predicate(run_id=_NO_RUN, flow_id=flow_id)


def flow_has_active_hold(flow_id: sa.ColumnElement[UUID] | Any) -> sa.Exists:
    """True while the Flow, or any of its runs, has an active hold."""
    return (
        sa.select(sa.literal(1))
        .select_from(FlowRetentionHolds)
        .where(FlowRetentionHolds.flow_id == flow_id)
        .where(flow_retention_hold_is_active())
        .exists()
    )


class FlowRetentionHoldRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def require_flow(self, *, tenant_id: UUID, flow_id: UUID) -> None:
        """A deleted Flow is accepted: its history still exists and can be held."""
        found = await self.session.scalar(
            sa.select(Flows.id)
            .where(Flows.id == flow_id)
            .where(Flows.tenant_id == tenant_id)
        )
        if found is None:
            raise NotFoundException("Flow not found.")

    async def max_review_days(self, *, tenant_id: UUID) -> int:
        flow_settings = await self.session.scalar(
            sa.select(Tenants.flow_settings).where(Tenants.id == tenant_id)
        )
        return resolve_flow_retention_policy(
            flow_settings
        ).effective_hold_max_review_days()

    async def runs_of_flow(
        self, *, tenant_id: UUID, flow_id: UUID, run_ids: Sequence[UUID]
    ) -> set[UUID]:
        result = await self.session.scalars(
            sa.select(FlowRuns.id)
            .where(FlowRuns.id.in_(run_ids))
            .where(FlowRuns.flow_id == flow_id)
            .where(FlowRuns.tenant_id == tenant_id)
            # A run whose deletion has started answers like a missing run.
            .where(FlowRuns.retention_receipt_id.is_(None))
        )
        return set(result.all())

    async def insert(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID,
        run_ids: Sequence[UUID | None],
        reason: str,
        review_by: datetime,
        ends_at: datetime | None,
        actor: dict[str, Any],
        user_id: UUID | None,
    ) -> list[UUID]:
        result = await self.session.scalars(
            sa.insert(FlowRetentionHolds)
            .values(
                [
                    {
                        "tenant_id": tenant_id,
                        "flow_id": flow_id,
                        "flow_run_id": run_id,
                        "reason": reason,
                        "review_by": review_by,
                        "ends_at": ends_at,
                        "created_by_actor": actor,
                        "created_by_user_id": user_id,
                    }
                    for run_id in run_ids
                ]
            )
            .returning(FlowRetentionHolds.id)
        )
        return list(result.all())

    async def set_review_by(
        self, *, tenant_id: UUID, hold_id: UUID, review_by: datetime
    ) -> None:
        await self.session.execute(
            sa.update(FlowRetentionHolds)
            .where(FlowRetentionHolds.id == hold_id)
            .where(FlowRetentionHolds.tenant_id == tenant_id)
            .values(review_by=review_by)
        )

    async def lock_for_change(
        self, *, tenant_id: UUID, hold_id: UUID
    ) -> FlowRetentionHold:
        row = (
            await self.session.execute(
                self._select()
                .where(FlowRetentionHolds.id == hold_id)
                .where(FlowRetentionHolds.tenant_id == tenant_id)
                .with_for_update(of=FlowRetentionHolds)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException("Legal hold not found.")
        return self._to_domain(row)

    async def release(
        self,
        *,
        tenant_id: UUID,
        hold_id: UUID,
        reason: str,
        actor: dict[str, Any],
        user_id: UUID | None,
    ) -> None:
        await self.session.execute(
            sa.update(FlowRetentionHolds)
            .where(FlowRetentionHolds.id == hold_id)
            .where(FlowRetentionHolds.tenant_id == tenant_id)
            .where(FlowRetentionHolds.released_at.is_(None))
            .values(
                released_at=sa.func.now(),
                released_by_actor=actor,
                released_by_user_id=user_id,
                release_reason=reason,
            )
        )

    async def get_many(
        self, *, tenant_id: UUID, hold_ids: Sequence[UUID]
    ) -> list[FlowRetentionHold]:
        rows = (
            await self.session.execute(
                self._select()
                .where(FlowRetentionHolds.id.in_(hold_ids))
                .where(FlowRetentionHolds.tenant_id == tenant_id)
                .order_by(FlowRetentionHolds.created_at, FlowRetentionHolds.id)
            )
        ).all()
        by_id = {hold.id: hold for hold in map(self._to_domain, rows)}
        return [by_id[hold_id] for hold_id in hold_ids if hold_id in by_id]

    async def list(
        self,
        *,
        tenant_id: UUID,
        status: FlowRetentionHoldStatusFilter,
        flow_id: UUID | None,
        limit: int,
        offset: int,
    ) -> FlowRetentionHoldPage:
        stmt = self._select().where(FlowRetentionHolds.tenant_id == tenant_id)
        if status is FlowRetentionHoldStatusFilter.ACTIVE:
            stmt = stmt.where(flow_retention_hold_is_active())
        if flow_id is not None:
            stmt = stmt.where(FlowRetentionHolds.flow_id == flow_id)
        rows = (
            await self.session.execute(
                stmt.order_by(
                    FlowRetentionHolds.created_at.desc(), FlowRetentionHolds.id.desc()
                )
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        return FlowRetentionHoldPage(
            items=[self._to_domain(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
            review_limit_days=await self.max_review_days(tenant_id=tenant_id),
        )

    @staticmethod
    def _select() -> sa.Select[Any]:
        # Columns, not the ORM entity: a release updates the row in place, and
        # the identity map would hand back the pre-release object.
        return sa.select(
            FlowRetentionHolds.id,
            FlowRetentionHolds.flow_id,
            FlowRetentionHolds.flow_run_id,
            FlowRetentionHolds.reason,
            FlowRetentionHolds.review_by,
            FlowRetentionHolds.ends_at,
            FlowRetentionHolds.created_at,
            FlowRetentionHolds.created_by_actor,
            FlowRetentionHolds.released_at,
            FlowRetentionHolds.released_by_actor,
            FlowRetentionHolds.release_reason,
            Flows.name.label("flow_name"),
            Flows.space_id.label("space_id"),
            Flows.deleted_at.is_not(None).label("flow_retired"),
            flow_retention_hold_is_active().label("active"),
            flow_retention_hold_review_overdue().label("review_overdue"),
        ).join(
            Flows,
            sa.and_(
                Flows.id == FlowRetentionHolds.flow_id,
                Flows.tenant_id == FlowRetentionHolds.tenant_id,
            ),
        )

    @staticmethod
    def _to_domain(row: sa.Row[Any]) -> FlowRetentionHold:
        return FlowRetentionHold(
            id=row.id,
            flow_id=row.flow_id,
            flow_name=row.flow_name,
            flow_retired=row.flow_retired,
            space_id=row.space_id,
            flow_run_id=row.flow_run_id,
            reason=row.reason,
            review_by=row.review_by,
            review_overdue=row.review_overdue,
            ends_at=row.ends_at,
            created_at=row.created_at,
            created_by=flow_retention_hold_actor(row.created_by_actor),
            released_at=row.released_at,
            released_by=flow_retention_hold_actor(row.released_by_actor),
            release_reason=row.release_reason,
            active=row.active,
        )
