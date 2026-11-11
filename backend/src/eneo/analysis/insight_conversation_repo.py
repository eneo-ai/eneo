"""Async SQLAlchemy repository for ``insight_conversations``.

Tenant-scoped: every read applies ``tenant_id`` as a WHERE clause. The
table carries its own ``tenant_id`` so the filter is a plain equality; this
is intentionally not shared with ``SessionRepository._filter_by_tenant``,
which solves the different problem of principal-less api-key sessions.
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict

from eneo.analysis.insight_scope import InsightTargetKind
from eneo.database.database import AsyncSession
from eneo.database.tables.insight_conversations_table import InsightConversations
from eneo.database.tables.sessions_table import Sessions
from eneo.main.exceptions import BadRequestException
from eneo.sessions.session import SessionMetadataPublic

_CURSOR_SEPARATOR = "_"


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


class InsightConversationPage(NamedTuple):
    items: list[SessionMetadataPublic]
    total: int
    # Where the next page starts, or None on the last page.
    next_cursor: str | None


def encode_cursor(created_at: datetime, session_id: UUID) -> str:
    """The position after one listed conversation, as an opaque string."""
    return f"{created_at.isoformat()}{_CURSOR_SEPARATOR}{session_id}"


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """The position :func:`encode_cursor` wrote; 400 for anything else."""
    created_at, _, session_id = cursor.rpartition(_CURSOR_SEPARATOR)
    try:
        position = (datetime.fromisoformat(created_at), UUID(session_id))
    except ValueError:
        raise BadRequestException("Invalid cursor")
    if position[0].tzinfo is None:
        raise BadRequestException("Invalid cursor")
    return position


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

    async def list_for_actor(
        self,
        *,
        tenant_id: UUID,
        actor_user_id: UUID,
        assistant_id: UUID | None = None,
        group_chat_id: UUID | None = None,
        limit: int,
        cursor: str | None = None,
    ) -> InsightConversationPage:
        """The operator's own conversations about one target, newest first.

        Keyset-paged on the link row's ``(created_at, session_id)``, which is
        unique, so a page boundary between two conversations started in the
        same instant loses neither. The cursor is opaque to the client.
        """
        if (assistant_id is None) == (group_chat_id is None):
            raise ValueError(
                "Exactly one of assistant_id or group_chat_id is required."
            )
        base = (
            sa.select(
                Sessions.id,
                Sessions.name,
                Sessions.created_at,
                Sessions.updated_at,
                InsightConversations.created_at.label("listed_at"),
            )
            .join(InsightConversations, InsightConversations.session_id == Sessions.id)
            .where(
                InsightConversations.tenant_id == tenant_id,
                InsightConversations.actor_user_id == actor_user_id,
            )
        )
        if assistant_id is not None:
            base = base.where(InsightConversations.assistant_id == assistant_id)
        else:
            base = base.where(InsightConversations.group_chat_id == group_chat_id)

        total = await self.session.scalar(
            sa.select(sa.func.count()).select_from(base.subquery())
        )
        page_stmt = base.order_by(
            InsightConversations.created_at.desc(),
            InsightConversations.session_id.desc(),
        )
        if cursor is not None:
            listed_at, session_id = decode_cursor(cursor)
            created = InsightConversations.created_at
            page_stmt = page_stmt.where(
                sa.or_(
                    created < listed_at,
                    sa.and_(
                        created == listed_at,
                        InsightConversations.session_id < session_id,
                    ),
                )
            )
        rows = (await self.session.execute(page_stmt.limit(limit + 1))).all()
        page = rows[:limit]
        next_cursor = (
            encode_cursor(page[-1].listed_at, page[-1].id)
            if len(rows) > limit and page
            else None
        )
        return InsightConversationPage(
            items=[
                SessionMetadataPublic(
                    id=row.id,
                    name=row.name,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in page
            ],
            total=int(total or 0),
            next_cursor=next_cursor,
        )

    async def get_by_session_id(
        self, session_id: UUID, tenant_id: UUID
    ) -> InsightConversation | None:
        stmt = sa.select(InsightConversations).where(
            InsightConversations.session_id == session_id,
            InsightConversations.tenant_id == tenant_id,
        )
        row = await self.session.scalar(stmt)
        return InsightConversation.model_validate(row) if row is not None else None
