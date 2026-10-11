"""Bound discovery before checking or locking orphaned conversation sessions."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.data_retention.constants import ORPHANED_SESSION_CLEANUP_DAYS
from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions


class OrphanSessionRetentionRepository:
    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self.session = session
        self.now = now
        self.grace = timedelta(days=ORPHANED_SESSION_CLEANUP_DAYS)

    def _unreferenced(self) -> ColumnElement[bool]:
        return (
            ~sa.select(Questions.id).where(Questions.session_id == Sessions.id).exists()
        )

    async def window(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> Sequence[RetentionKeyset]:
        statement = sa.select(Sessions.id, Sessions.created_at).where(
            Sessions.created_at < self.now - self.grace
        )
        if cursor is not None:
            statement = statement.where(
                sa.tuple_(Sessions.created_at, Sessions.id) > (cursor.at, cursor.id)
            )
        statement = statement.order_by(Sessions.created_at, Sessions.id).limit(limit)
        rows = (await self.session.execute(statement)).tuples().all()
        return tuple(RetentionKeyset(id=identifier, at=at) for identifier, at in rows)

    async def lock_orphans(self, ids: Sequence[UUID]) -> Mapping[UUID, int]:
        # The helper's UNIQUE session_id bounds its cascade to at most one row.
        cost = 1 + sa.case((HelpAssistantRuns.id.is_not(None), 1), else_=0)
        statement = (
            sa.select(Sessions.id, cost)
            .outerjoin(HelpAssistantRuns, HelpAssistantRuns.session_id == Sessions.id)
            .where(
                uuid_in(Sessions.id, ids),
                Sessions.created_at < self.now - self.grace,
                self._unreferenced(),
            )
            .with_for_update(of=Sessions, skip_locked=True)
        )
        return dict((await self.session.execute(statement)).tuples().all())

    async def delete_due(self, ids: Sequence[UUID]) -> Sequence[UUID]:
        statement = (
            sa.delete(Sessions)
            .where(
                uuid_in(Sessions.id, ids),
                Sessions.created_at < self.now - self.grace,
                self._unreferenced(),
            )
            .returning(Sessions.id)
        )
        return tuple((await self.session.scalars(statement)).all())
