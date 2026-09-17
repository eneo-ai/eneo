from datetime import date
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.widgets_table import Widgets


class WidgetDailyUsage(BasePublic):
    # Persisted after each answer settles; Redis holds the live counters.
    widget_id: Mapped[UUID] = mapped_column(ForeignKey(Widgets.id, ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(sa.Date())
    questions: Mapped[int] = mapped_column(server_default="0")
    input_tokens: Mapped[int] = mapped_column(server_default="0")
    output_tokens: Mapped[int] = mapped_column(server_default="0")
    blocked_budget: Mapped[int] = mapped_column(server_default="0")
    blocked_rate: Mapped[int] = mapped_column(server_default="0")

    __table_args__ = (
        UniqueConstraint("widget_id", "day", name="uq_widget_daily_usage_widget_day"),
    )
