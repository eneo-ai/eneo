"""Async SQLAlchemy repository for ``insight_conversations``.

Tenant-scoped: every read applies ``tenant_id`` as a WHERE clause. The
table carries its own ``tenant_id`` so the filter is a plain equality; this
is intentionally not shared with ``SessionRepository._filter_by_tenant``,
which solves the different problem of principal-less api-key sessions.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict

from eneo.analysis.insight_scope import InsightTargetKind
from eneo.database.database import AsyncSession
from eneo.database.tables.insight_conversations_table import InsightConversations


class InsightConversation(BaseModel):
    """One insights analysis conversation's link row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    session_id: UUID
    assistant_id: UUID | None
    group_chat_id: UUID | None
    actor_user_id: UUID | None
    completion_model_id: UUID | None
    timezone: str
    created_at: datetime
    updated_at: datetime

    @property
    def target_kind(self) -> InsightTargetKind:
        return "assistant" if self.assistant_id is not None else "group_chat"

    @property
    def target_id(self) -> UUID:
        target = (
            self.assistant_id if self.assistant_id is not None else self.group_chat_id
        )
        assert target is not None
        return target


class InsightConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        tenant_id: UUID,
        session_id: UUID,
        actor_user_id: UUID,
        timezone: str,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
        completion_model_id: UUID | None = None,
    ) -> InsightConversation:
        if (assistant_id is None) == (group_chat_id is None):
            raise ValueError(
                "Exactly one of assistant_id or group_chat_id is required."
            )
        stmt = (
            sa.insert(InsightConversations)
            .values(
                tenant_id=tenant_id,
                session_id=session_id,
                assistant_id=assistant_id,
                group_chat_id=group_chat_id,
                actor_user_id=actor_user_id,
                completion_model_id=completion_model_id,
                timezone=timezone,
            )
            .returning(InsightConversations)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        return InsightConversation.model_validate(row)

    async def get_by_session_id(
        self, session_id: UUID, tenant_id: UUID
    ) -> InsightConversation | None:
        stmt = sa.select(InsightConversations).where(
            InsightConversations.session_id == session_id,
            InsightConversations.tenant_id == tenant_id,
        )
        row = await self.session.scalar(stmt)
        return InsightConversation.model_validate(row) if row is not None else None
