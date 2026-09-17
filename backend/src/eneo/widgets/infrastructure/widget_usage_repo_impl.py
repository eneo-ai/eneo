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
from eneo.database.tables.widget_usage_table import WidgetDailyUsage
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

    async def list_days(self, widget_id: UUID, *, days: int) -> list[WidgetUsageDay]:
        since = date.today() - timedelta(days=max(0, days - 1))
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
            if days > 0:
                targets.append((widget_id, days))
        return targets

    @staticmethod
    def cutoff_for(retention_days: int, now: datetime | None = None) -> datetime:
        return (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
