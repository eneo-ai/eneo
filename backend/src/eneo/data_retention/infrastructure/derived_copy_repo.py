"""Discovery and the fresh check for copies whose source was removed.

A copy session is invalid once one of its edges points at a question that no
longer exists. Question ids never return, so it stays invalid. Discovery walks
the edges in the order of their unique index, which bounds every window by the
rows it returns; the bounded removal of each question is the shared
conversation unit's.
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from eneo.data_retention.application.conversation_retention import (
    ConversationDeletion,
    ConversationPage,
    ConversationRootKind,
    ConversationUnitResult,
    is_past_owner,
    past_owner,
)
from eneo.data_retention.application.retention_runner import RetentionContractError
from eneo.data_retention.derivations import (
    copy_session_valid,
    probe,
    source_removed,
)
from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.data_retention.infrastructure.conversation_unit_repo import (
    ConversationUnitRepository,
)
from eneo.data_retention.infrastructure.retention_sql import (
    question_in_widget,
    uuid_in,
)
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.retention_tables import ContentDerivations
from eneo.database.tables.sessions_table import Sessions

# An edge position: every edge up to (session, source) was examined. A cursor
# at any other time is a question of an invalid copy, continued after it.
_EDGE_AT = datetime.min.replace(tzinfo=timezone.utc)
_FIRST = datetime.min.replace(tzinfo=timezone.utc)


def edge_position(copy_session_id: UUID, source_question_id: UUID) -> RetentionKeyset:
    return RetentionKeyset(at=_EDGE_AT, id=source_question_id, group=copy_session_id)


def _continues_copy(cursor: RetentionKeyset) -> bool:
    return cursor.at != _EDGE_AT and not is_past_owner(cursor)


class CopyEdge(NamedTuple):
    id: UUID
    copy_session_id: UUID
    source_question_id: UUID
    session_removed: bool
    source_removed: bool


class DerivedCopyRepository:
    kind = ConversationRootKind.QUESTION
    examined_key = "edges_examined"

    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self.session = session
        self.unit = ConversationUnitRepository(
            session, kind=ConversationRootKind.QUESTION, now=now
        )

    async def edge_window(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> Sequence[CopyEdge]:
        """The next `limit` edges in index order, each with whether its copy
        session and its source still exist."""
        statement = sa.select(
            ContentDerivations.id,
            ContentDerivations.copy_session_id,
            ContentDerivations.source_question_id,
            (~probe(Sessions.id == ContentDerivations.copy_session_id)).label(
                "session_removed"
            ),
            source_removed().label("source_removed"),
        )
        if cursor is not None:
            if cursor.group is None:
                raise RetentionContractError(
                    "A copy keyset must identify its copy session."
                )
            statement = statement.where(
                ContentDerivations.copy_session_id > cursor.group
                if is_past_owner(cursor)
                else sa.tuple_(
                    ContentDerivations.copy_session_id,
                    ContentDerivations.source_question_id,
                )
                > (cursor.group, cursor.id)
            )
        rows = await self.session.execute(
            statement.order_by(
                ContentDerivations.copy_session_id,
                ContentDerivations.source_question_id,
            ).limit(limit)
        )
        return tuple(CopyEdge._make(row) for row in rows.tuples())

    def _lock_statement(
        self,
        copies: Sequence[UUID],
        continued: RetentionKeyset | None,
        limit: int,
    ) -> sa.Select[tuple[UUID, datetime, UUID, UUID | None, bool]]:
        """At most `limit` questions of the copies in (session, created_at, id)
        order, the continued copy's after its cursor, locked unless passed."""
        sessions = (
            sa.select(Sessions.id)
            .where(
                uuid_in(Sessions.id, copies),
                Sessions.id.between(min(copies), max(copies)),
            )
            .order_by(Sessions.id)
            .subquery("invalid_copies")
        )
        questions = sa.select(
            Questions.id,
            Questions.created_at,
            question_in_widget().label("passed"),
        ).where(Questions.session_id == sessions.c.id)
        if continued is not None:
            questions = questions.where(
                sa.tuple_(Questions.created_at, Questions.id)
                > sa.tuple_(
                    sa.case(
                        (sessions.c.id == continued.group, continued.at),
                        else_=_FIRST,
                    ),
                    sa.case(
                        (sessions.c.id == continued.group, continued.id),
                        else_=UUID(int=0),
                    ),
                )
            )
        roots = (
            questions.order_by(Questions.created_at, Questions.id)
            .limit(limit)
            .correlate(sessions)
            .lateral("copy_questions")
        )
        window = (
            sa.select(
                roots.c.id,
                roots.c.created_at,
                sessions.c.id.label("session_id"),
                roots.c.passed,
            )
            .select_from(sessions.join(roots, sa.true()))
            .order_by(sessions.c.id, roots.c.created_at, roots.c.id)
            .limit(limit)
            .cte("copy_window")
            .prefix_with("MATERIALIZED")
        )
        locked = (
            sa.select(Questions.id.label("locked_id"))
            .where(Questions.id == window.c.id, ~window.c.passed)
            .with_for_update(of=Questions, skip_locked=True)
            .correlate(window)
            .lateral("locked_copy_question")
        )
        return (
            sa.select(
                window.c.id,
                window.c.created_at,
                window.c.session_id,
                locked.c.locked_id,
                window.c.passed,
            )
            .select_from(window.outerjoin(locked, sa.true()))
            .order_by(window.c.session_id, window.c.created_at, window.c.id)
        )

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage:
        """Questions of the invalid copies among the next `limit` edges.

        A cursor at a question continues that copy without checking it again,
        then reads the edges of the copies after it.
        """
        continued = cursor if cursor is not None and _continues_copy(cursor) else None
        known: tuple[UUID, ...] = ()
        if continued is not None:
            if continued.group is None:
                raise RetentionContractError(
                    "A copy keyset must identify its copy session."
                )
            known = (continued.group,)
            cursor = past_owner(continued.group)
        edges = await self.edge_window(cursor, limit)
        copies = sorted(
            {
                *known,
                *(
                    edge.copy_session_id
                    for edge in edges
                    if edge.source_removed and not edge.session_removed
                ),
            }
        )
        if not edges and not copies:
            return ConversationPage(
                roots=(), locked_ids=(), examined=0, done=None, complete=True
            )
        rows = (
            (await self.session.execute(self._lock_statement(copies, continued, limit)))
            .tuples()
            .all()
            if copies
            else ()
        )
        last = edges[-1] if edges else None
        return ConversationPage(
            roots=tuple(
                RetentionKeyset(at=at, id=identifier, group=copy)
                for identifier, at, copy, _locked, _passed in rows
            ),
            locked_ids=tuple(
                locked for *_, locked, _passed in rows if locked is not None
            ),
            examined=len(edges),
            done=edge_position(last.copy_session_id, last.source_question_id)
            if last is not None
            else past_owner(copies[-1]),
            complete=len(edges) < limit,
            passed_ids=tuple(identifier for identifier, *_, passed in rows if passed),
        )

    def _still_selected(self, identifier: UUID) -> list[ColumnElement[bool]]:
        # Each condition keeps the question selected inside the DELETE's
        # snapshot; another reason to keep a question is one more condition.
        return [
            Questions.id == identifier,
            ~question_in_widget(),
            ~copy_session_valid(Questions.session_id.expression),
        ]

    async def delete_if_still_removed(
        self, identifier: UUID
    ) -> ConversationDeletion | None:
        row = (
            (
                await self.session.execute(
                    sa.delete(Questions)
                    .where(*self._still_selected(identifier))
                    .returning(Questions.id, Questions.tenant_id)
                )
            )
            .tuples()
            .one_or_none()
        )
        if row is None:
            return None
        deleted_id, tenant_id = row
        return ConversationDeletion(id=deleted_id, tenant_id=tenant_id, source=None)

    async def cascade_cost(self, identifier: UUID, ceiling: int) -> int:
        return await self.unit.cascade_cost(identifier, ceiling)

    async def delete_unit(
        self,
        identifier: UUID,
        *,
        child_rows: int,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> ConversationUnitResult:
        return await self.unit.delete_unit(
            identifier,
            delete=self.delete_if_still_removed,
            child_rows=child_rows,
            max_rows=max_rows,
            max_files=max_files,
            max_family_rows=max_family_rows,
        )

    async def delete_edges_of_removed_sessions(self, ids: Sequence[UUID]) -> int:
        """Delete these edges if their copy session is gone; a session id never
        returns, so such an edge can never be needed again."""
        deleted = await self.session.scalars(
            sa.delete(ContentDerivations)
            .where(
                uuid_in(ContentDerivations.id, ids),
                ~probe(Sessions.id == ContentDerivations.copy_session_id),
            )
            .returning(ContentDerivations.id)
        )
        return len(deleted.all())
