from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.service_table import Services
from eneo.database.tables.users_table import Users
from eneo.database.tables.widgets_table import Widgets

if TYPE_CHECKING:
    from eneo.database.tables.questions_table import Questions


class Sessions(BasePublic):
    # user_id is nullable so service-key sessions (which authenticate via an
    # API key, not a real user) can be persisted. api_key_id carries the
    # owning principal in that case. Exactly one of the two is set per row.
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="CASCADE"), nullable=True
    )
    api_key_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(ApiKeysV2.id, ondelete="SET NULL"), nullable=True
    )
    # Widget sessions: the principal is the widget plus a pseudonymous
    # visitor id; neither a user nor an API key is involved.
    widget_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Widgets.id, ondelete="CASCADE"), nullable=True
    )
    visitor_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column()
    feedback_value: Mapped[Optional[int]] = mapped_column()
    feedback_text: Mapped[Optional[str]] = mapped_column()

    # Foreign keys
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE")
    )
    service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Services.id, ondelete="CASCADE")
    )
    group_chat_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(GroupChatsTable.id, ondelete="CASCADE")
    )

    # Relationships
    questions: Mapped[list["Questions"]] = relationship(order_by="Questions.created_at")
    assistant: Mapped[Optional[Assistants]] = relationship(
        foreign_keys="Sessions.assistant_id", viewonly=True
    )
    group_chat: Mapped[Optional[GroupChatsTable]] = relationship(viewonly=True)

    __table_args__ = (
        Index("created_at_idx", "created_at"),
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (api_key_id IS NOT NULL)::int"
            " + (widget_id IS NOT NULL)::int = 1",
            name="ck_sessions_single_principal",
        ),
        CheckConstraint(
            "(visitor_id IS NULL) = (widget_id IS NULL)",
            name="ck_sessions_visitor_requires_widget",
        ),
        Index(
            "ix_sessions_widget_visitor_created",
            "widget_id",
            "visitor_id",
            sa.text("created_at DESC"),
        ),
    )
