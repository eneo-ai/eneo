"""Human-owned chat bindings: a person's helper chat on one target."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import TIMESTAMP, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BaseCrossReference
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class HelperChats(BaseCrossReference):
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE"), primary_key=True
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), unique=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True
    )
    space_id: Mapped[UUID] = mapped_column(ForeignKey(Spaces.id, ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey(Users.id, ondelete="CASCADE"))
    # What the chat helps with: a kind (``HelperChatTargetType``) and the id of
    # that kind's row. The id has no foreign key, since it names rows of
    # different tables; the target's own deletion removes its chats.
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID] = mapped_column()
    editing: Mapped[bool] = mapped_column(default=False, server_default="false")
    # The person's own model for the chat; null follows the organisation's
    # default for the target's chats, then the space's.
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="SET NULL"), nullable=True
    )
    reasoning_effort: Mapped[Optional[str]] = mapped_column(nullable=True)
    # When the person last turned edit mode on or off. The return to view
    # mode after a pause leaves it, so the pause still counts.
    mode_changed_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "target_type",
            "target_id",
            name="uq_helper_chat_owner",
        ),
    )
