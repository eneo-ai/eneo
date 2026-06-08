from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.api_keys_v2_table import ApiKeysV2
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.base_class import BasePublic
from intric.database.tables.group_chats_table import GroupChatsTable
from intric.database.tables.service_table import Services
from intric.database.tables.users_table import Users

if TYPE_CHECKING:
    from intric.database.tables.questions_table import Questions


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
            "(user_id IS NOT NULL) <> (api_key_id IS NOT NULL)",
            name="ck_sessions_user_xor_api_key",
        ),
    )
