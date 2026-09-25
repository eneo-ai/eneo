# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import SQLColumnExpression
from sqlalchemy.orm import aliased

from eneo.database.database import AsyncSession
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.database.tables.widget_usage_table import WidgetDailyUsage
from eneo.database.tables.widgets_table import Widgets
from eneo.spaces.oversight.oversight_models import OversightPersonRef
from eneo.spaces.space_reads import SpaceKind, space_kind
from eneo.widgets.domain.widget import Widget, WidgetStatus
from eneo.widgets.infrastructure.widget_repo_impl import to_entity


@dataclass(frozen=True)
class WidgetOverviewRow:
    widget: Widget
    # Whether the assistant behind the widget is published; None when it no
    # longer exists.
    target_published: Optional[bool]
    id: UUID
    public_id: str
    name: str
    status: str
    space_id: UUID
    space_name: Optional[str]
    space_kind: SpaceKind
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
    activation_requested_at: Optional[datetime] = None
    # None when nobody asked, or the user who asked was deleted.
    activation_requested_by: Optional[OversightPersonRef] = None


@dataclass(frozen=True)
class WidgetReviewRow:
    overview: WidgetOverviewRow
    created_by: Optional[OversightPersonRef]
    activated_by: Optional[OversightPersonRef]
    activation_declined_by: Optional[OversightPersonRef]


def _person_columns(alias: Any, prefix: str) -> list[Any]:
    return [
        alias.id.label(f"{prefix}_id"),
        alias.username.label(f"{prefix}_username"),
        alias.email.label(f"{prefix}_email"),
    ]


def _person(row: Any, prefix: str) -> Optional[OversightPersonRef]:
    id = getattr(row, f"{prefix}_id")
    email = getattr(row, f"{prefix}_email")
    if id is None or email is None:
        return None
    username = getattr(row, f"{prefix}_username")
    return OversightPersonRef(id=id, name=username or email, email=email)


def _live_user(alias: Any, user_id: Any) -> sa.ColumnElement[bool]:
    return sa.and_(alias.id == user_id, alias.deleted_at.is_(None))


class WidgetOverviewRepoImpl:
    """Every widget of a tenant with where it lives and its recent usage."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _select(self, tenant_id: UUID, *, today: date) -> sa.Select[Any]:
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

        requester = aliased(Users)
        return (
            sa.select(
                Widgets,
                Spaces.name.label("space_name"),
                Spaces.user_id.label("space_owner_id"),
                Spaces.tenant_space_id.label("space_parent_id"),
                Assistants.name.label("assistant_name"),
                Assistants.published.label("assistant_published"),
                aggregates.c.questions_7d,
                aggregates.c.questions_30d,
                aggregates.c.input_tokens_30d,
                aggregates.c.output_tokens_30d,
                aggregates.c.blocked_30d,
                aggregates.c.helpful_30d,
                aggregates.c.unhelpful_30d,
                aggregates.c.last_activity,
                aggregates.c.budget_used_today,
                *_person_columns(requester, "requester"),
            )
            .outerjoin(Spaces, Spaces.id == Widgets.space_id)
            .outerjoin(Assistants, Assistants.id == Widgets.target_id)
            .outerjoin(aggregates, aggregates.c.widget_id == Widgets.id)
            .outerjoin(
                requester,
                _live_user(requester, Widgets.activation_requested_by_user_id),
            )
            .where(Widgets.tenant_id == tenant_id)
        )

    @staticmethod
    def _row(row: Any) -> WidgetOverviewRow:
        widget: Widgets = row[0]
        entity = to_entity(widget)
        return WidgetOverviewRow(
            widget=entity,
            target_published=row.assistant_published,
            id=widget.id,
            public_id=widget.public_id,
            name=widget.name,
            status=widget.status,
            space_id=widget.space_id,
            space_name=row.space_name,
            space_kind=space_kind(row.space_owner_id, row.space_parent_id),
            target_id=widget.target_id,
            assistant_name=row.assistant_name,
            allowed_origins=list(widget.allowed_origins or []),
            daily_token_budget=entity.limits.daily_token_budget,
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
            activation_requested_at=widget.activation_requested_at,
            activation_requested_by=_person(row, "requester"),
        )

    async def list_tenant(
        self, tenant_id: UUID, *, today: date
    ) -> list[WidgetOverviewRow]:
        """Pending activation requests first (oldest first), then active
        widgets, then the most recently changed."""
        stmt = self._select(tenant_id, today=today).order_by(
            Widgets.activation_requested_at.asc().nulls_last(),
            sa.case((Widgets.status == WidgetStatus.ACTIVE.value, 0), else_=1),
            Widgets.updated_at.desc(),
        )
        rows = await self.session.execute(stmt)
        return [self._row(row) for row in rows]

    async def get_one(
        self, tenant_id: UUID, widget_id: UUID, *, today: date
    ) -> Optional[WidgetReviewRow]:
        """One widget of the tenant with its usage and the people behind its
        lifecycle; None for another tenant's widget."""
        creator = aliased(Users)
        activator = aliased(Users)
        decliner = aliased(Users)
        stmt = (
            self._select(tenant_id, today=today)
            .add_columns(
                *_person_columns(creator, "creator"),
                *_person_columns(activator, "activator"),
                *_person_columns(decliner, "decliner"),
            )
            .outerjoin(creator, _live_user(creator, Widgets.created_by_user_id))
            .outerjoin(activator, _live_user(activator, Widgets.activated_by_user_id))
            .outerjoin(
                decliner,
                _live_user(decliner, Widgets.activation_declined_by_user_id),
            )
            .where(Widgets.id == widget_id)
        )
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return WidgetReviewRow(
            overview=self._row(row),
            created_by=_person(row, "creator"),
            activated_by=_person(row, "activator"),
            activation_declined_by=_person(row, "decliner"),
        )
