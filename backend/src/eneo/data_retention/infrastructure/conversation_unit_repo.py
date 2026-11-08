"""The bounded removal of one conversation root, shared by every selection.

A selection discovers and locks roots and owns the fresh check inside the root
DELETE; this unit proves the cascade, captures the root's Files and session,
runs the DELETE in a savepoint and releases what it emptied.
"""

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import import_module
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import count

from eneo.data_retention.application.conversation_retention import (
    CONVERSATION_FILE_BLOCKS,
    ConversationBlockReason,
    ConversationDeletion,
    ConversationRootKind,
    ConversationUnitResult,
)
from eneo.data_retention.application.retention_runner import is_lock_wait_timeout
from eneo.data_retention.infrastructure.empty_session_repo import (
    EmptySessionRepository,
)
from eneo.database.tables.app_table import AppRuns, AppRunsFiles
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.files.file_retention import FileRetentionReason
from eneo.files.file_usage import FileUsageRepository


class ConversationCascadeError(RuntimeError):
    """A foreign key to a conversation root does not cascade with its deletion."""


def collect_conversation_children(
    metadata: sa.MetaData, root: sa.Table
) -> tuple[sa.Column[UUID], ...]:
    """Every foreign key to a conversation root, from the schema metadata.

    The bounded proof counts and charges these rows, and the root DELETE relies
    on each of them cascading: a key that restricts or nulls would fail every
    unit or leave rows behind, so it fails here, at import, instead.
    """
    children: list[sa.Column[UUID]] = []
    for table in metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table is not root:
                continue
            column = foreign_key.parent
            if foreign_key.ondelete != "CASCADE":
                raise ConversationCascadeError(
                    f"{table.name}.{column.name} references {root.name} without "
                    "ON DELETE CASCADE: conversation retention deletes the root "
                    "and relies on the cascade"
                )
            children.append(column)
    return tuple(sorted(children, key=lambda column: (column.table.name, column.name)))


def _root_table(model: type[Questions] | type[AppRuns]) -> sa.Table:
    table = sa.inspect(model, raiseerr=True).local_table
    if not isinstance(table, sa.Table):
        raise TypeError(f"{model.__name__} must map directly to a SQL table.")
    return table


# Every table module must be registered on the metadata before scanning it.
import_module("eneo.database.tables")
_QUESTIONS_TABLE = _root_table(Questions)
QUESTION_CHILDREN = collect_conversation_children(
    _QUESTIONS_TABLE.metadata, _QUESTIONS_TABLE
)
_APP_RUNS_TABLE = _root_table(AppRuns)
APP_RUN_CHILDREN = collect_conversation_children(
    _APP_RUNS_TABLE.metadata, _APP_RUNS_TABLE
)


@dataclass(frozen=True, slots=True)
class _SessionRelease:
    rows: int
    deleted: int


# The selection's fresh DELETE of one root: the deletion when the root was
# still selected inside the DELETE's snapshot, else None.
FreshRootDelete = Callable[[UUID], Awaitable[ConversationDeletion | None]]


class ConversationUnitRepository:
    def __init__(
        self, session: AsyncSession, *, kind: ConversationRootKind, now: datetime
    ) -> None:
        self.session = session
        self.kind = kind
        self.now = now
        self.records: type[Questions] | type[AppRuns]
        self.children: tuple[sa.Column[UUID], ...]
        self.file_id: ColumnElement[UUID]
        self.file_owner_id: ColumnElement[UUID]
        # The session a root belongs to, removed with its last question.
        self.root_session: ColumnElement[UUID | None] | None
        if kind is ConversationRootKind.QUESTION:
            self.records = Questions
            self.file_id = QuestionsFiles.file_id.expression
            self.file_owner_id = QuestionsFiles.question_id.expression
            self.children = QUESTION_CHILDREN
            self.root_session = Questions.session_id.expression
        else:
            self.records = AppRuns
            self.file_id = AppRunsFiles.file_id.expression
            self.file_owner_id = AppRunsFiles.app_run_id.expression
            self.children = APP_RUN_CHILDREN
            self.root_session = None

    async def cascade_cost(self, identifier: UUID, ceiling: int) -> int:
        # One LIMIT over every child relation: the proof examines at most
        # ceiling + 1 rows, whatever the number of relations.
        children = (
            sa.union_all(
                *(
                    sa.select(foreign_key).where(foreign_key == identifier)
                    for foreign_key in self.children
                )
            )
            .limit(ceiling + 1)
            .subquery("conversation_children")
        )
        return await self.session.scalar(sa.select(count()).select_from(children)) or 0

    async def _release_emptied_session(self, session_id: UUID) -> _SessionRelease:
        """Delete the session its last question left empty.

        The empty-session owner's lock and DELETE apply, its no-question
        predicate repeated in the DELETE. A session a live chat holds, or that
        still has a question, is left to that owner's sweep. Charges one row for
        the lock and proof, then the session and its UNIQUE helper row: at most
        `EmptySessionRepository.MAX_RELEASE_ROWS`, which `delete_unit` reserves
        first.
        """
        # No grace: the session held a question that was due, so it is no new
        # chat waiting for its first question. The no-question predicate is the
        # check the release must repeat.
        sessions = EmptySessionRepository(
            self.session, now=self.now, grace=timedelta(0)
        )
        cost = (await sessions.lock_empty((session_id,))).get(session_id)
        if cost is None:
            return _SessionRelease(rows=1, deleted=0)
        deleted = await sessions.delete_due((session_id,))
        return _SessionRelease(rows=1 + cost, deleted=len(deleted))

    async def delete_unit(
        self,
        identifier: UUID,
        *,
        delete: FreshRootDelete,
        child_rows: int,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> ConversationUnitResult:
        """Delete one proved root, its emptied session and its Files within `max_rows`.

        `delete` is the selection's fresh DELETE of the root. The proof already
        charged every child row, which bounds the link read and the cascade;
        this charges the root DELETE, the session and the Files work. A unit
        whose remainder cannot fund the root DELETE with a session release, or
        that has Files and no file allowance, does not fit before anything is
        deleted; one whose Files cannot fit rolls back whole, and so does one
        whose cascade waits past the lock timeout on a row another transaction
        holds.
        """
        # The locked conversation fences new link rows, so its links are among
        # the proved children. Capture them, and the root's session, before the
        # DELETE removes them; discovery already charged the root row.
        file_ids = tuple(
            await self.session.scalars(
                sa.select(self.file_id)
                .where(self.file_owner_id == identifier)
                .limit(child_rows)
            )
        )
        session_id = (
            await self.session.scalar(
                sa.select(self.root_session).where(self.records.id == identifier)
            )
            if self.root_session is not None
            else None
        )
        # Refuse what the remainder cannot fund before the root DELETE, so such
        # a unit writes nothing it would roll back.
        if (
            session_id is not None
            and max_rows - 1 < EmptySessionRepository.MAX_RELEASE_ROWS
        ) or (file_ids and max_files == 0):
            return ConversationUnitResult(rows=0, files=0, fits=False)
        # `rows` charges the statements that completed; `attempt` bounds what
        # the statement in flight may read. A lock wait's own reads are
        # unknown, but each phase has a proved or configured bound, so the
        # unit is charged that bound and the chunk can admit the next root.
        rows = 0
        files = 0
        # The root DELETE re-examines the root and at most its proved cascade.
        attempt = 1 + child_rows
        try:
            async with self.session.begin_nested() as unit:
                deletion = await delete(identifier)
                rows = 1
                if deletion is None:
                    return ConversationUnitResult(
                        rows=rows,
                        files=0,
                        block=ConversationBlockReason.NO_LONGER_DUE,
                    )
                sessions_deleted = 0
                if session_id is not None:
                    attempt = EmptySessionRepository.MAX_RELEASE_ROWS
                    released = await self._release_emptied_session(session_id)
                    rows += released.rows
                    sessions_deleted = released.deleted
                file_outcomes: Counter[FileRetentionReason] = Counter()
                usage = FileUsageRepository(self.session)
                for file_id in sorted(set(file_ids)):
                    # A family release reads at most its allowance and its cap.
                    attempt = min(max_rows - rows, max_family_rows)
                    result = await usage.delete_unused_root(
                        file_id,
                        max_rows=max_rows - rows,
                        max_files=max_files - files,
                        max_family_rows=max_family_rows,
                    )
                    rows += result.rows
                    files += result.files
                    if result.needs_rollback:
                        await unit.rollback()
                        return ConversationUnitResult(
                            rows=rows,
                            files=files,
                            fits=result.reason
                            is not FileRetentionReason.INSUFFICIENT_BUDGET,
                            block=result.reason
                            if result.reason in CONVERSATION_FILE_BLOCKS
                            else None,
                        )
                    if result.reason is not FileRetentionReason.DELETED:
                        file_outcomes[result.reason] += 1
                return ConversationUnitResult(
                    rows=rows,
                    files=files,
                    deletion=deletion,
                    sessions_deleted=sessions_deleted,
                    files_deleted=files,
                    file_outcomes=file_outcomes,
                )
        except DBAPIError as error:
            if not is_lock_wait_timeout(error):
                raise
            # Leaving the block rolled the savepoint back, which also restores
            # the transaction.
            return ConversationUnitResult(
                rows=min(max_rows, rows + attempt),
                files=files,
                block=ConversationBlockReason.CASCADE_LOCKED,
            )
