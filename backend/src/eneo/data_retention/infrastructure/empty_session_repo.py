"""Bound discovery before checking or locking sessions without a question."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.data_retention.infrastructure.retention_sql import outside_widgets, uuid_in
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions


class EmptySessionRepository:
    # The most one session's release reads and deletes: its lock and proof, the
    # session row and its UNIQUE help-assistant helper row. Every caller that
    # funds a release before locking reserves this much.
    MAX_RELEASE_ROWS: Final = 3

    def __init__(
        self, session: AsyncSession, *, now: datetime, grace: timedelta
    ) -> None:
        self.session = session
        self.now = now
        self.grace = grace

    def _unreferenced(self) -> ColumnElement[bool]:
        return (
            ~sa.select(Questions.id).where(Questions.session_id == Sessions.id).exists()
        )

    def _releasable(self, ids: Sequence[UUID]) -> tuple[ColumnElement[bool], ...]:
        """Which of these sessions are empty and due: one rule for the lock, the
        count of what the lock skipped, and the delete."""
        return (
            uuid_in(Sessions.id, ids),
            Sessions.created_at < self.now - self.grace,
            self._unreferenced(),
            outside_widgets(),
        )

    async def window(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> Sequence[tuple[RetentionKeyset, bool]]:
        """The next `limit` sessions past the grace period in keyset order, each
        with whether a widget owns it (to be passed: widget retention removes
        it). The keyset index reads exactly the rows returned, so retained
        widget sessions never make one window an unbounded read; the lock and
        the delete refuse them again."""
        statement = sa.select(
            Sessions.id, Sessions.created_at, (~outside_widgets()).label("passed")
        ).where(Sessions.created_at < self.now - self.grace)
        if cursor is not None:
            statement = statement.where(
                sa.tuple_(Sessions.created_at, Sessions.id) > (cursor.at, cursor.id)
            )
        statement = statement.order_by(Sessions.created_at, Sessions.id).limit(limit)
        rows = (await self.session.execute(statement)).tuples().all()
        return tuple(
            (RetentionKeyset(id=identifier, at=at), passed)
            for identifier, at, passed in rows
        )

    async def lock_empty(self, ids: Sequence[UUID]) -> Mapping[UUID, int]:
        # The helper's UNIQUE session_id bounds its cascade to at most one row.
        cost = 1 + sa.case((HelpAssistantRuns.id.is_not(None), 1), else_=0)
        statement = (
            sa.select(Sessions.id, cost)
            .outerjoin(HelpAssistantRuns, HelpAssistantRuns.session_id == Sessions.id)
            .where(*self._releasable(ids))
            .with_for_update(of=Sessions, skip_locked=True)
        )
        return dict((await self.session.execute(statement)).tuples().all())

    async def count_empty(self, ids: Sequence[UUID]) -> int:
        """How many of these sessions are still empty and due, without locking:
        those another transaction held while lock_empty skipped them."""
        statement = (
            sa.select(sa.func.count())
            .select_from(Sessions)
            .where(*self._releasable(ids))
        )
        return (await self.session.execute(statement)).scalar_one()

    async def delete_due(self, ids: Sequence[UUID]) -> Sequence[UUID]:
        statement = (
            sa.delete(Sessions).where(*self._releasable(ids)).returning(Sessions.id)
        )
        return tuple((await self.session.scalars(statement)).all())
