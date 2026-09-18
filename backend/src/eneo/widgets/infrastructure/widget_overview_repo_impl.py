# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import SQLColumnExpression

from eneo.database.database import AsyncSession
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.widget_usage_table import WidgetDailyUsage
from eneo.database.tables.widgets_table import Widgets


@dataclass(frozen=True)
class WidgetOverviewRow:
    id: UUID
    public_id: str
    name: str
    status: str
    space_id: UUID
    space_name: Optional[str]
    target_id: UUID
    assistant_name: Optional[str]
    allowed_origins: list[str]
    daily_token_budget: int
    budget_used_today: int
    activated_at: Optional[datetime]
    paused_at: Optional[datetime]
    updated_at: datetime
    questions_7d: int
    questions_30d: int
    input_tokens_30d: int
    output_tokens_30d: int
    blocked_30d: int
    helpful_30d: int
    unhelpful_30d: int
    last_activity: Optional[date]


class WidgetOverviewRepoImpl:
    """Every widget of a tenant with where it lives and its recent usage."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_tenant(
        self, tenant_id: UUID, *, today: date
    ) -> list[WidgetOverviewRow]:
        since_7 = today - timedelta(days=6)
        since_30 = today - timedelta(days=29)
        usage = WidgetDailyUsage

        def window_sum(column: SQLColumnExpression[int], since: date):
            return sa.func.coalesce(sa.func.sum(column).filter(usage.day >= since), 0)

        aggregates = (
            sa.select(
                usage.widget_id.label("widget_id"),
                window_sum(usage.questions, since_7).label("questions_7d"),
                window_sum(usage.questions, since_30).label("questions_30d"),
                window_sum(usage.input_tokens, since_30).label("input_tokens_30d"),
                window_sum(usage.output_tokens, since_30).label("output_tokens_30d"),
                window_sum(usage.blocked_budget + usage.blocked_rate, since_30).label(
                    "blocked_30d"
                ),
                window_sum(usage.helpful, since_30).label("helpful_30d"),
                window_sum(usage.unhelpful, since_30).label("unhelpful_30d"),
                sa.func.max(usage.day)
                .filter(usage.questions + usage.blocked_budget + usage.blocked_rate > 0)
                .label("last_activity"),
                sa.func.coalesce(
                    sa.func.sum(
                        usage.input_tokens + usage.output_tokens + usage.reserved_tokens
                    ).filter(usage.day == today),
                    0,
                ).label("budget_used_today"),
            )
            .join(Widgets, Widgets.id == usage.widget_id)
            .where(Widgets.tenant_id == tenant_id)
            .group_by(usage.widget_id)
            .subquery()
        )

        stmt = (
            sa.select(
                Widgets,
                Spaces.name.label("space_name"),
                Assistants.name.label("assistant_name"),
                aggregates.c.questions_7d,
                aggregates.c.questions_30d,
                aggregates.c.input_tokens_30d,
                aggregates.c.output_tokens_30d,
                aggregates.c.blocked_30d,
                aggregates.c.helpful_30d,
                aggregates.c.unhelpful_30d,
                aggregates.c.last_activity,
                aggregates.c.budget_used_today,
            )
            .outerjoin(Spaces, Spaces.id == Widgets.space_id)
            .outerjoin(Assistants, Assistants.id == Widgets.target_id)
            .outerjoin(aggregates, aggregates.c.widget_id == Widgets.id)
            .where(Widgets.tenant_id == tenant_id)
            .order_by(
                sa.case((Widgets.status == "active", 0), else_=1),
                Widgets.updated_at.desc(),
            )
        )
        rows = await self.session.execute(stmt)
        result: list[WidgetOverviewRow] = []
        for row in rows:
            widget: Widgets = row[0]
            limits = widget.limits or {}
            result.append(
                WidgetOverviewRow(
                    id=widget.id,
                    public_id=widget.public_id,
                    name=widget.name,
                    status=widget.status,
                    space_id=widget.space_id,
                    space_name=row.space_name,
                    target_id=widget.target_id,
                    assistant_name=row.assistant_name,
                    allowed_origins=list(widget.allowed_origins or []),
                    daily_token_budget=int(limits.get("daily_token_budget", 500_000)),
                    budget_used_today=int(row.budget_used_today or 0),
                    activated_at=widget.activated_at,
                    paused_at=widget.paused_at,
                    updated_at=widget.updated_at,
                    questions_7d=int(row.questions_7d or 0),
                    questions_30d=int(row.questions_30d or 0),
                    input_tokens_30d=int(row.input_tokens_30d or 0),
                    output_tokens_30d=int(row.output_tokens_30d or 0),
                    blocked_30d=int(row.blocked_30d or 0),
                    helpful_30d=int(row.helpful_30d or 0),
                    unhelpful_30d=int(row.unhelpful_30d or 0),
                    last_activity=row.last_activity,
                )
            )
        return result
