from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class InsightConversations(BasePublic):
    """Link row marking a ``sessions`` row as an insights analysis conversation.

    One-to-one with a ``sessions`` row (``session_id`` UNIQUE). The session
    itself carries the operator as ``user_id`` and the analysed assistant or
    group chat as its partner, so cascade and retention behave like any other
    conversation; this row is what keeps it out of every normal session,
    conversation and analytics listing (see
    :mod:`eneo.sessions.hidden_sessions`). ``tenant_id`` is explicit so the
    hot listing and retention paths need no join. Exactly one of
    ``assistant_id`` / ``group_chat_id`` is set (CHECK constraint), and both
    cascade so the conversation disappears with its target.
    ``actor_user_id`` and ``completion_model_id`` are ``SET NULL`` to survive
    user removal and model retirement.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey(Sessions.id, ondelete="CASCADE"), nullable=False
    )
    assistant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Assistants.id, ondelete="CASCADE"), nullable=True
    )
    group_chat_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(GroupChatsTable.id, ondelete="CASCADE"), nullable=True
    )
    actor_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="SET NULL"), nullable=True
    )
    completion_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="SET NULL"), nullable=True
    )
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_insight_conversations_session_id"),
        CheckConstraint(
            "(assistant_id IS NOT NULL) <> (group_chat_id IS NOT NULL)",
            name="ck_insight_conversations_target_xor",
        ),
        Index(
            "ix_insight_conversations_target_actor_created_at",
            "tenant_id",
            "assistant_id",
            "group_chat_id",
            "actor_user_id",
            text("created_at DESC"),
        ),
    )
