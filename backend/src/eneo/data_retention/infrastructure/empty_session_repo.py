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
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.database.tables.insight_conversations_table import InsightConversations
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions


class EmptySessionRepository:
    # The most one session's release reads and deletes: its lock and proof, the
    # session row and the one row its deletion cascades to, a help assistant's
    # run, a helper chat or an insights conversation's link (each
    # UNIQUE on the session, and each makes its own session). Every caller that
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
        with whether another owner removes it, to be passed. Widget retention
        removes a widget's session, and the lock and the delete refuse it again.
        Conversation history removes a helper chat's session with its last
        question; before its first one the chat is empty, and its model and
        edit mode live in a row the session's deletion cascades to. An insights
        conversation is made with its first question, so an empty one is left
        over and goes like any other session, its link row with it. The keyset
        index reads exactly the rows returned, so passed sessions never make one
        window an unbounded read."""
        helper_chat = (
            sa.select(HelperChats.session_id)
            .where(HelperChats.session_id == Sessions.id)
            .exists()
        )
        statement = sa.select(
            Sessions.id,
            Sessions.created_at,
            (~outside_widgets() | helper_chat).label("passed"),
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
        # The help assistant's, the helper chat's and the insights link's UNIQUE
        # session_id bound each cascade to at most one row.
        cost = (
            1
            + sa.case((HelpAssistantRuns.id.is_not(None), 1), else_=0)
            + sa.case((HelperChats.session_id.is_not(None), 1), else_=0)
            + sa.case((InsightConversations.id.is_not(None), 1), else_=0)
        )
        statement = (
            sa.select(Sessions.id, cost)
            .outerjoin(HelpAssistantRuns, HelpAssistantRuns.session_id == Sessions.id)
            .outerjoin(HelperChats, HelperChats.session_id == Sessions.id)
            .outerjoin(
                InsightConversations, InsightConversations.session_id == Sessions.id
            )
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
