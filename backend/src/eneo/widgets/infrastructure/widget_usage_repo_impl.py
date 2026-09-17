# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult

from eneo.database.database import AsyncSession
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.widget_usage_table import (
    WidgetBudgetReservations,
    WidgetDailyUsage,
)
from eneo.database.tables.widgets_table import Widgets


@dataclass(frozen=True)
class WidgetUsageDay:
    day: date
    questions: int
    input_tokens: int
    output_tokens: int
    blocked_budget: int
    blocked_rate: int


class WidgetUsageRepoImpl:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self,
        reservation_id: UUID,
        widget_id: UUID,
        day: date,
        *,
        tokens: int,
        limit: int,
    ) -> bool:
        usage = WidgetDailyUsage
        await self.session.execute(
            insert(usage)
            .values(widget_id=widget_id, day=day)
            .on_conflict_do_nothing(constraint="uq_widget_daily_usage_widget_day")
        )
        # The conditional UPDATE serializes concurrent admissions on this day.
        admitted = await self.session.scalar(
            sa.update(usage)
            .where(
                usage.widget_id == widget_id,
                usage.day == day,
                usage.input_tokens
                + usage.output_tokens
                + usage.reserved_tokens
                + tokens
                <= limit,
            )
            .values(reserved_tokens=usage.reserved_tokens + tokens)
            .returning(usage.id)
        )
        if admitted is None:
            return False
        await self.session.execute(
            sa.insert(WidgetBudgetReservations).values(
                id=reservation_id,
                widget_id=widget_id,
                day=day,
                tokens=tokens,
            )
        )
        return True

    async def finish_reservation(
        self,
        reservation_id: UUID,
        *,
        input_tokens: int,
        output_tokens: int,
        released: bool = False,
    ) -> None:
        receipt = await self.session.scalar(
            sa.select(WidgetBudgetReservations)
            .where(WidgetBudgetReservations.id == reservation_id)
            .with_for_update()
        )
        if receipt is None or receipt.state != "reserved":
            return
        usage = WidgetDailyUsage
        await self.session.execute(
            sa.update(usage)
            .where(usage.widget_id == receipt.widget_id, usage.day == receipt.day)
            .values(
                reserved_tokens=usage.reserved_tokens - receipt.tokens,
                questions=usage.questions + (0 if released else 1),
                input_tokens=usage.input_tokens + max(0, input_tokens),
                output_tokens=usage.output_tokens + max(0, output_tokens),
            )
        )
        receipt.state = "released" if released else "settled"

    async def budget_used(self, widget_id: UUID, day: date) -> int:
        usage = WidgetDailyUsage
        value = await self.session.scalar(
            sa.select(
                usage.input_tokens + usage.output_tokens + usage.reserved_tokens
            ).where(usage.widget_id == widget_id, usage.day == day)
        )
        return int(value or 0)

    async def prune_budget_receipts(self, before: date) -> None:
        # Old uncertain reservations stay charged in the daily totals; only
        # their content-free idempotency receipts expire.
        await self.session.execute(
            sa.delete(WidgetBudgetReservations).where(
                WidgetBudgetReservations.day < before
            )
        )

    async def record(
        self,
        widget_id: UUID,
        day: date,
        *,
        questions: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        blocked_budget: int = 0,
        blocked_rate: int = 0,
    ) -> None:
        stmt = insert(WidgetDailyUsage).values(
            widget_id=widget_id,
            day=day,
            questions=questions,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            blocked_budget=blocked_budget,
            blocked_rate=blocked_rate,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_widget_daily_usage_widget_day",
            set_={
                "questions": WidgetDailyUsage.questions + questions,
                "input_tokens": WidgetDailyUsage.input_tokens + input_tokens,
                "output_tokens": WidgetDailyUsage.output_tokens + output_tokens,
                "blocked_budget": WidgetDailyUsage.blocked_budget + blocked_budget,
                "blocked_rate": WidgetDailyUsage.blocked_rate + blocked_rate,
                "updated_at": sa.func.now(),
            },
        )
        await self.session.execute(stmt)

    async def list_days(
        self, widget_id: UUID, *, days: int, today: date
    ) -> list[WidgetUsageDay]:
        since = today - timedelta(days=max(0, days - 1))
        rows = await self.session.execute(
            sa.select(WidgetDailyUsage)
            .where(
                WidgetDailyUsage.widget_id == widget_id, WidgetDailyUsage.day >= since
            )
            .order_by(WidgetDailyUsage.day.desc())
        )
        return [
            WidgetUsageDay(
                day=row.day,
                questions=row.questions,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                blocked_budget=row.blocked_budget,
                blocked_rate=row.blocked_rate,
            )
            for row in rows.scalars()
        ]

    async def delete_sessions_before(self, widget_id: UUID, cutoff: datetime) -> int:
        """Widget sessions never own generated files (tools are off), so a
        plain delete cascades questions and references."""
        result = await self.session.execute(
            sa.delete(Sessions).where(
                Sessions.widget_id == widget_id, Sessions.created_at < cutoff
            )
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def delete_session(self, session_id: UUID) -> None:
        await self.session.execute(
            sa.delete(Sessions).where(
                Sessions.id == session_id, Sessions.widget_id.is_not(None)
            )
        )

    async def retention_targets(self) -> list[tuple[UUID, int]]:
        """(widget_id, retention_days) for every widget that keeps sessions
        for a bounded time; archived widgets are included so their history
        still expires."""
        rows = await self.session.execute(
            sa.select(Widgets.id, Widgets.privacy["retention_days"].as_integer())
        )
        targets: list[tuple[UUID, int]] = []
        for widget_id, retention in rows.all():
            days = int(retention) if retention is not None else 30
            targets.append((widget_id, days))
        return targets

    @staticmethod
    def cutoff_for(retention_days: int, now: datetime | None = None) -> datetime:
        return (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
