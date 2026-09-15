from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseWithTableName, TimestampMixin


class WhatsNewSeen(TimestampMixin, BaseWithTableName):
    """The newest release a user has opened on the What's new page.

    One row per user; the row is created on the first visit and rewritten on
    later ones, so ``updated_at`` doubles as "seen at".
    """

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
