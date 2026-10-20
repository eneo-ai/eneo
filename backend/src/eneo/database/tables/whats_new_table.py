from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, TimestampMixin


class WhatsNewState(TimestampMixin, BaseWithTableName):
    """Per-user What's new progress: one row per user, created on first touch.

    ``seen_version`` is the newest release the user has opened the page for
    (drives the "new updates" dot); ``announced_version`` is the newest
    release they have been shown the one-time announcement for. The two are
    independent: dismissing the announcement does not count as having looked.
    """

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    seen_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    announced_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
