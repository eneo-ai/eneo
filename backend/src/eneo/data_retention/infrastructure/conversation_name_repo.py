"""Conversation names and feedback texts past their own time.

A name is the first question, a title made from the turns or one the user set,
and feedback text can quote the turns. Each keeps the time it was last written
and goes once that time is older than the conversation's period, whether or not
its questions are still there. The name is replaced by an empty one, which both
apps show as untitled; the feedback vote stays.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import coalesce

from eneo.data_retention.domain.retention import RetentionKeyset
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

    def _due(self, ids: Sequence[UUID]) -> sa.Select[tuple[UUID, UUID, datetime]]:
        return (
            sa.select(Sessions.id, Spaces.tenant_id, self.cutoff.label("cutoff"))
            .select_from(Sessions)
            .outerjoin(Assistants, Assistants.id == Sessions.assistant_id)
            .outerjoin(GroupChatsTable, GroupChatsTable.id == Sessions.group_chat_id)
            .join(
                Spaces,
                Spaces.id == coalesce(GroupChatsTable.space_id, Assistants.space_id),
            )
            .outerjoin(
                AuditRetentionPolicy, AuditRetentionPolicy.tenant_id == Spaces.tenant_id
            )
            .where(
                uuid_in(Sessions.id, ids),
                outside_widgets(),
                self.days.is_not(None),
                sa.or_(_name_due(self.cutoff), _feedback_due(self.cutoff)),
            )
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

        Each write checks the field's own time against the cutoff again, so a
        rename or new feedback that lands first is kept."""
        names = await self._clear(ids, _name_due, name="")
        texts = await self._clear(ids, _feedback_due, feedback_text=None)
        return tuple(
            (session_id, tenant_id, session_id in names, session_id in texts)
            for session_id, tenant_id in {**names, **texts}.items()
        )

    async def _clear(
        self,
        ids: Sequence[UUID],
        is_due: Callable[[ColumnElement[datetime]], ColumnElement[bool]],
        **emptied: str | None,
    ) -> dict[UUID, UUID]:
        due = self._due(ids).with_for_update(of=Sessions, skip_locked=True).cte("due")
        statement = (
            sa.update(Sessions)
            .where(Sessions.id == due.c.id, is_due(due.c.cutoff))
            # Not a change by anyone: the conversation keeps its place.
            .values(**emptied, updated_at=Sessions.updated_at)
            .returning(Sessions.id, due.c.tenant_id)
        )
        return dict((await self.session.execute(statement)).tuples().all())

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
