"""Conversation names and feedback texts past their own time.

A name is the first question, a title made from the turns or one the user set,
and feedback text can quote the turns. Each keeps the time it was last written
and goes once that time is older than the conversation's period, whether or not
its questions are still there. The name is replaced by an empty one, which both
apps show as untitled; the feedback vote stays.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, TypeVar, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import coalesce

from eneo.data_retention.domain.retention import RetentionKeyset, RetentionOverdue
from eneo.data_retention.infrastructure.conversation_retention_policy import (
    conversation_retention_policy,
)
from eneo.data_retention.infrastructure.retention_sql import outside_widgets, uuid_in
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces

_Row = TypeVar("_Row", bound=tuple[Any, ...])


class ConversationNameRepository:
    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self.session = session
        # The period of the space and organisation around the conversation.
        around = conversation_retention_policy(
            cast("ColumnElement[int | None]", sa.null())
        ).days
        member = aliased(Assistants)
        # A group chat's turns come from its assistants, each on its own
        # period, so its name keeps no longer than the shortest of them.
        shortest_member = (
            sa.select(sa.func.min(coalesce(member.data_retention_days, around)))
            .select_from(GroupChatsAssistantsMapping)
            .join(member, member.id == GroupChatsAssistantsMapping.assistant_id)
            .where(GroupChatsAssistantsMapping.group_chat_id == Sessions.group_chat_id)
            .scalar_subquery()
        )
        days = conversation_retention_policy(
            sa.case(
                (Sessions.group_chat_id.is_not(None), shortest_member),
                else_=Assistants.data_retention_days,
            )
        ).days
        self.cutoff = now - sa.func.make_interval(0, 0, 0, days)
        self.days = days

    def _under_a_period(self, statement: sa.Select[_Row]) -> sa.Select[_Row]:
        """The conversations outside widgets that have a period, with their
        space and organisation's policy joined."""
        return (
            statement.select_from(Sessions)
            .outerjoin(Assistants, Assistants.id == Sessions.assistant_id)
            .outerjoin(GroupChatsTable, GroupChatsTable.id == Sessions.group_chat_id)
            .join(
                Spaces,
                Spaces.id == coalesce(GroupChatsTable.space_id, Assistants.space_id),
            )
            .outerjoin(
                AuditRetentionPolicy, AuditRetentionPolicy.tenant_id == Spaces.tenant_id
            )
            .where(outside_widgets(), self.days.is_not(None))
        )

    def _due(self, ids: Sequence[UUID]) -> sa.Select[tuple[UUID, UUID, datetime]]:
        return self._under_a_period(
            sa.select(Sessions.id, Spaces.tenant_id, self.cutoff.label("cutoff"))
        ).where(
            uuid_in(Sessions.id, ids),
            sa.or_(_name_due(self.cutoff), _feedback_due(self.cutoff)),
        )

    async def window(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> Sequence[tuple[RetentionKeyset, bool]]:
        """The next `limit` conversations in keyset order, each with whether a
        widget owns it (to be passed: widget retention removes it). The keyset
        index reads exactly the rows returned."""
        statement = sa.select(
            Sessions.id, Sessions.created_at, (~outside_widgets()).label("passed")
        )
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

    async def clear_due(
        self, ids: Sequence[UUID]
    ) -> Sequence[tuple[UUID, UUID, bool, bool]]:
        """Empty each due name and feedback text of these conversations that no
        other transaction holds: the id and tenant of each conversation written
        and which of the two went.

        Both go in one write of the row, which checks each field's own time
        against the cutoff again, so a rename or new feedback that lands first
        is kept."""
        due = (
            self._due(ids)
            .add_columns(
                _name_due(self.cutoff).label("name_due"),
                _feedback_due(self.cutoff).label("feedback_due"),
            )
            .with_for_update(of=Sessions, skip_locked=True)
            .cte("due")
        )
        name_due = _name_due(due.c.cutoff)
        feedback_due = _feedback_due(due.c.cutoff)
        statement = (
            sa.update(Sessions)
            .where(Sessions.id == due.c.id, sa.or_(name_due, feedback_due))
            .values(
                name=sa.case((name_due, ""), else_=Sessions.name),
                feedback_text=sa.case(
                    (feedback_due, None), else_=Sessions.feedback_text
                ),
                # Not a change by anyone: the conversation keeps its place.
                updated_at=Sessions.updated_at,
            )
            # The returned values are the new ones; which field went comes from
            # the CTE, which holds the row's lock and so read the version this
            # write checks.
            .returning(Sessions.id, due.c.tenant_id, due.c.name_due, due.c.feedback_due)
        )
        return tuple((await self.session.execute(statement)).tuples().all())

    async def overdue(self, *, window: timedelta, limit: int) -> RetentionOverdue:
        """Conversations with a name or feedback text still stored past its
        time and `window`, up to `limit`.

        One statement of at most `limit + 1` rows and no locks: a conversation
        another transaction holds is still overdue. No index serves a cutoff
        that depends on each conversation's period, so the statement reads
        conversations until it has `limit + 1` (all of them when fewer are
        overdue), bounded by the transaction's statement timeout like the
        step that clears them.
        """
        cutoff = self.cutoff - window
        name_overdue = _name_due(cutoff)
        feedback_overdue = _feedback_due(cutoff)
        # The older overdue text; a field with nothing to remove keeps its
        # time (an emptied name, a vote without text), so it does not count.
        set_at = sa.func.least(
            sa.case((name_overdue, Sessions.name_set_at)),
            sa.case((feedback_overdue, Sessions.feedback_set_at)),
        )
        due_at = sa.type_coerce(
            set_at + sa.func.make_interval(0, 0, 0, self.days),
            sa.DateTime(timezone=True),
        )
        statement = (
            self._under_a_period(sa.select(due_at))
            .where(sa.or_(name_overdue, feedback_overdue))
            .limit(limit + 1)
        )
        found = (await self.session.scalars(statement)).all()
        covered = found[:limit]
        return RetentionOverdue(
            count=len(covered),
            complete=len(found) <= limit,
            oldest_due_at=min(covered) if covered else None,
        )

    async def count_due(self, ids: Sequence[UUID]) -> int:
        """How many of these conversations still have a due name or feedback
        text, without locking: those another transaction held."""
        statement = sa.select(sa.func.count()).select_from(self._due(ids).subquery())
        return (await self.session.execute(statement)).scalar_one()


def _name_due(cutoff: ColumnElement[datetime]) -> ColumnElement[bool]:
    return sa.and_(Sessions.name != "", Sessions.name_set_at < cutoff)


def _feedback_due(cutoff: ColumnElement[datetime]) -> ColumnElement[bool]:
    return sa.and_(
        Sessions.feedback_text.is_not(None), Sessions.feedback_set_at < cutoff
    )
