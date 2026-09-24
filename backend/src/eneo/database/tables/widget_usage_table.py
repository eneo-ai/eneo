from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.widgets_table import Widgets


class WidgetDailyUsage(BasePublic):
    # Both completed usage and in-flight budget charges are durable.
    widget_id: Mapped[UUID] = mapped_column(ForeignKey(Widgets.id, ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(sa.Date())
    questions: Mapped[int] = mapped_column(server_default="0")
    input_tokens: Mapped[int] = mapped_column(server_default="0")
    output_tokens: Mapped[int] = mapped_column(server_default="0")
    blocked_budget: Mapped[int] = mapped_column(server_default="0")
    blocked_rate: Mapped[int] = mapped_column(server_default="0")
    reserved_tokens: Mapped[int] = mapped_column(server_default="0")
    # Votes on the conversations started that day; a changed vote moves
    # between them.
    helpful: Mapped[int] = mapped_column(server_default="0")
    unhelpful: Mapped[int] = mapped_column(server_default="0")

    __table_args__ = (
        UniqueConstraint("widget_id", "day", name="uq_widget_daily_usage_widget_day"),
        CheckConstraint("reserved_tokens >= 0", name="ck_widget_usage_reserved_tokens"),
    )


class WidgetBudgetReservations(BasePublic):
    """One durable receipt per admitted turn; contains no visitor or chat data."""

    widget_id: Mapped[UUID] = mapped_column()
    day: Mapped[date] = mapped_column(sa.Date())
    tokens: Mapped[int] = mapped_column()
    state: Mapped[str] = mapped_column(server_default="reserved")

    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["widget_id", "day"],
            ["widget_daily_usage.widget_id", "widget_daily_usage.day"],
            ondelete="CASCADE",
        ),
        CheckConstraint("tokens >= 0", name="ck_widget_reservation_tokens"),
        CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_widget_reservation_state",
        ),
        Index("ix_widget_budget_reservations_day", "day"),
    )
