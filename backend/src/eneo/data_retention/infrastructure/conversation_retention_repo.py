"""Locked pages and fresh deletes for the two conversation root stores."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from importlib import import_module
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import count
from sqlalchemy.sql.selectable import CTE

from eneo.data_retention.application.conversation_retention import (
    ConversationBlockReason,
    ConversationDeletion,
    ConversationPage,
    ConversationUnitResult,
    is_past_owner,
    past_owner,
)
from eneo.data_retention.application.retention_runner import RetentionContractError
from eneo.data_retention.domain.conversation_policy import ConversationPolicySource
from eneo.data_retention.domain.retention import (
    RetentionKeyset,
    RetentionOverdue,
)
from eneo.data_retention.infrastructure.conversation_retention_policy import (
    conversation_retention_policy,
)
from eneo.data_retention.infrastructure.orphan_session_retention_repo import (
    OrphanSessionRetentionRepository,
)
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.spaces_table import Spaces
from eneo.files.file_retention import FileRetentionReason
from eneo.files.file_usage import FileUsageRepository


class ConversationRootKind(StrEnum):
    QUESTION = "question"
    APP_RUN = "app_run"


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
    fits: bool


class ConversationRetentionRepository:
    def __init__(
        self, session: AsyncSession, *, kind: ConversationRootKind, now: datetime
    ) -> None:
        self.session = session
        self.now = now
        self.records: type[Questions] | type[AppRuns]
        self.parent: type[Assistants] | type[Apps]
        self.parent_fk: ColumnElement[UUID] | ColumnElement[UUID | None]
        self.children: tuple[sa.Column[UUID], ...]
        self.file_id: ColumnElement[UUID]
        self.file_owner_id: ColumnElement[UUID]
        # The session a root belongs to, removed with its last question.
        self.root_session: ColumnElement[UUID | None] | None
        if kind is ConversationRootKind.QUESTION:
            self.records = Questions
            self.parent = Assistants
            self.parent_fk = Questions.assistant_id.expression
            self.file_id = QuestionsFiles.file_id.expression
            self.file_owner_id = QuestionsFiles.question_id.expression
            self.children = QUESTION_CHILDREN
            self.root_session = Questions.session_id.expression
        else:
            self.records = AppRuns
            self.parent = Apps
            self.parent_fk = AppRuns.app_id.expression
            self.file_id = AppRunsFiles.file_id.expression
            self.file_owner_id = AppRunsFiles.app_run_id.expression
            self.children = APP_RUN_CHILDREN
            self.root_session = None
        self.policy = conversation_retention_policy(
            self.parent.data_retention_days.expression
        )
        self.cutoff = self.now - sa.func.make_interval(0, 0, 0, self.policy.days)

    def _due(self) -> sa.Select[tuple[UUID, datetime, UUID, str | None]]:
        return (
            sa.select(
                self.records.id,
                self.records.created_at,
                self.parent.id.label("owner_id"),
                self.policy.source.label("policy_source"),
            )
            .join(self.parent, self.parent_fk == self.parent.id)
            .join(Spaces, self.parent.space_id == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                self.policy.days.is_not(None),
                self.records.created_at < self.cutoff,
            )
        )

    def _owners(
        self, overdue_window: timedelta = timedelta(0)
    ) -> sa.Select[tuple[UUID, datetime, int | None]]:
        """Owners with an effective policy, and the cutoff each one applies."""
        return (
            sa.select(
                self.parent.id,
                (self.cutoff - overdue_window).label("cutoff"),
                self.policy.days.label("days"),
            )
            .join(Spaces, self.parent.space_id == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(self.policy.days.is_not(None))
        )

    async def _owner_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> Sequence[UUID]:
        """At most `limit` owners in id order from the cursor's owner on (after
        it once all its roots were visited).

        Every owner of the kind, with or without a policy: a primary key range
        reads exactly the rows it returns, so charging each returned owner bounds
        the read. The window applies the policy to this page.
        """
        query = sa.select(self.parent.id)
        if cursor is not None:
            if cursor.group is None:
                raise RetentionContractError(
                    "A conversation keyset must identify its owner."
                )
            query = query.where(
                self.parent.id > cursor.group
                if is_past_owner(cursor)
                else self.parent.id >= cursor.group
            )
        return tuple(
            await self.session.scalars(query.order_by(self.parent.id).limit(limit))
        )

    def _window_statement(
        self,
        owner_ids: Sequence[UUID],
        cursor: RetentionKeyset | None,
        limit: int,
        overdue_window: timedelta = timedelta(0),
    ) -> CTE:
        # The id list alone is planned as a filter over every owner once the
        # table is large; the page's key range keeps it an index range scan.
        owners = (
            self._owners(overdue_window)
            .where(
                uuid_in(self.parent.id, owner_ids),
                self.parent.id.between(min(owner_ids), max(owner_ids)),
            )
            .order_by(self.parent.id)
            .subquery("conversation_owners")
        )
        due = sa.select(
            self.records.id,
            self.records.created_at,
            (
                self.records.created_at + sa.func.make_interval(0, 0, 0, owners.c.days)
            ).label("due_at"),
        ).where(
            self.parent_fk == owners.c.id,
            self.records.created_at < owners.c.cutoff,
        )
        if cursor is not None and not is_past_owner(cursor):
            # Keep the current owner's time bound usable as an index condition.
            lower_time = sa.case(
                (owners.c.id == cursor.group, cursor.at),
                else_=datetime.min.replace(tzinfo=self.now.tzinfo),
            )
            due = due.where(
                sa.tuple_(self.records.created_at, self.records.id)
                > sa.tuple_(
                    lower_time,
                    sa.case(
                        (owners.c.id == cursor.group, cursor.id), else_=UUID(int=0)
                    ),
                )
            )
        roots = (
            due.order_by(self.records.created_at, self.records.id)
            .limit(limit)
            .correlate(owners)
            .lateral("due_owner_conversations")
        )
        # Bound discovery before taking any locks, including across owner changes.
        return (
            sa.select(
                roots.c.id,
                roots.c.created_at,
                owners.c.id.label("owner_id"),
                roots.c.due_at,
            )
            .select_from(owners.join(roots, sa.true()))
            .order_by(owners.c.id, roots.c.created_at, roots.c.id)
            .limit(limit)
            .cte("conversation_window")
            .prefix_with("MATERIALIZED")
        )

    def _lock_statement(
        self, owner_ids: Sequence[UUID], cursor: RetentionKeyset | None, limit: int
    ) -> sa.Select[tuple[UUID, datetime, UUID, UUID | None]]:
        window = self._window_statement(owner_ids, cursor, limit)
        locked = (
            sa.select(self.records.id.label("locked_id"))
            .where(self.records.id == window.c.id)
            .with_for_update(of=self.records, skip_locked=True)
            .correlate(window)
            .lateral("locked_conversation")
        )
        return (
            sa.select(
                window.c.id, window.c.created_at, window.c.owner_id, locked.c.locked_id
            )
            .select_from(window.outerjoin(locked, sa.true()))
            .order_by(window.c.owner_id, window.c.created_at, window.c.id)
        )

    async def overdue(
        self, *, window: timedelta, limit: int, owner_page: int
    ) -> RetentionOverdue:
        """Due work past `window` over every owner, up to `limit` rows.

        Pages of `owner_page` owners, each statement bounded, until the owners
        end or `limit + 1` rows are found. The page does not follow `limit`, so
        a small remaining cap does not cost two statements per owner. This reads
        O(owners) once per execution, in its own transaction outside the budget;
        capping the owners instead would make a deployment with many owners read
        incomplete, and so `unknown` in health, every night.
        """
        found: list[datetime] = []
        cursor: RetentionKeyset | None = None
        while True:
            owner_ids = await self._owner_page(cursor, owner_page)
            if owner_ids:
                candidates = self._window_statement(
                    owner_ids, None, limit + 1 - len(found), window
                )
                deadline = sa.type_coerce(
                    candidates.c.due_at, sa.DateTime(timezone=True)
                )
                found.extend(
                    await self.session.scalars(
                        sa.select(deadline).order_by(
                            candidates.c.owner_id,
                            candidates.c.created_at,
                            candidates.c.id,
                        )
                    )
                )
            if len(found) > limit or len(owner_ids) < owner_page:
                break
            cursor = past_owner(owner_ids[-1])
        covered = found[:limit]
        return RetentionOverdue(
            count=len(covered),
            complete=len(found) <= limit,
            oldest_due_at=min(covered) if covered else None,
        )

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage:
        owner_ids = await self._owner_page(cursor, limit)
        if not owner_ids:
            return ConversationPage(
                roots=(), locked_ids=(), owners_probed=0, last_owner=None
            )
        rows = (
            (await self.session.execute(self._lock_statement(owner_ids, cursor, limit)))
            .tuples()
            .all()
        )
        return ConversationPage(
            roots=tuple(
                RetentionKeyset(at=at, id=identifier, group=owner)
                for identifier, at, owner, _locked in rows
            ),
            locked_ids=tuple(
                locked for _id, _at, _owner, locked in rows if locked is not None
            ),
            owners_probed=len(owner_ids),
            last_owner=owner_ids[-1],
        )

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

    async def delete_due_prefix(
        self, ids: Sequence[UUID]
    ) -> Sequence[ConversationDeletion]:
        # Re-read policy in the DELETE snapshot, after discovery and proof.
        fresh = (
            self._due()
            .where(uuid_in(self.records.id, ids))
            .cte("current_due_conversations")
        )
        statement = (
            sa.delete(self.records)
            .where(self.records.id == fresh.c.id)
            .returning(
                self.records.id,
                self.records.tenant_id,
                sa.type_coerce(fresh.c.policy_source, sa.String()),
            )
        )
        rows = (await self.session.execute(statement)).tuples().all()
        return tuple(
            ConversationDeletion(
                id=identifier,
                tenant_id=tenant_id,
                source=ConversationPolicySource(source),
            )
            for identifier, tenant_id, source in rows
        )

    async def _release_emptied_session(
        self, session_id: UUID, allowance: int
    ) -> _SessionRelease:
        """Delete the session its last question left empty, within `allowance`.

        The empty-session owner's lock and DELETE apply, its no-question
        predicate repeated in the DELETE. A session a live chat holds, or that
        still has a question, is left to that owner's sweep. Charges one row for
        the lock and proof, then the session and its UNIQUE helper row.
        """
        if allowance < 1:
            return _SessionRelease(rows=0, deleted=0, fits=False)
        sessions = OrphanSessionRetentionRepository(self.session, now=self.now)
        cost = (await sessions.lock_orphans((session_id,))).get(session_id)
        if cost is None:
            return _SessionRelease(rows=1, deleted=0, fits=True)
        if 1 + cost > allowance:
            return _SessionRelease(rows=1, deleted=0, fits=False)
        deleted = await sessions.delete_due((session_id,))
        return _SessionRelease(rows=1 + cost, deleted=len(deleted), fits=True)

    async def delete_unit(
        self,
        identifier: UUID,
        *,
        child_rows: int,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
    ) -> ConversationUnitResult:
        """Delete one proved root, its emptied session and its Files within `max_rows`.

        The proof already charged every child row, which bounds the link read
        and the cascade; this charges the root DELETE, the session and the Files
        work. A unit that cannot fit them rolls back whole.
        """
        # The locked conversation fences new link rows, so its links are among
        # the proved children. Capture them, and the root's session, before the
        # DELETE removes them; discovery already charged the root row. A failed
        # admission must also restore the root.
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
        rows = 1
        files = 0
        sessions_deleted = 0
        file_outcomes: Counter[FileRetentionReason] = Counter()
        block: ConversationBlockReason | None = None
        async with self.session.begin_nested() as unit:
            deleted = await self.delete_due_prefix((identifier,))
            if not deleted:
                return ConversationUnitResult(
                    rows=rows,
                    files=0,
                    block=ConversationBlockReason.NO_LONGER_DUE,
                )
            if session_id is not None:
                released = await self._release_emptied_session(
                    session_id, max_rows - rows
                )
                rows += released.rows
                if not released.fits:
                    await unit.rollback()
                    return ConversationUnitResult(rows=rows, files=0, fits=False)
                sessions_deleted = released.deleted
            usage = FileUsageRepository(self.session)
            for file_id in sorted(set(file_ids)):
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
                        block=(
                            ConversationBlockReason.FILE_FAMILY_EXCEEDS_BUDGET
                            if result.reason
                            is FileRetentionReason.FAMILY_EXCEEDS_BUDGET
                            else ConversationBlockReason.FILE_LOCKED
                            if result.reason is FileRetentionReason.LOCKED
                            else None
                        ),
                    )
                if result.reason is FileRetentionReason.TENANT_MISMATCH:
                    block = ConversationBlockReason.FILE_TENANT_MISMATCH
                if result.reason is not FileRetentionReason.DELETED:
                    file_outcomes[result.reason] += 1
            return ConversationUnitResult(
                rows=rows,
                files=files,
                deletion=deleted[0],
                sessions_deleted=sessions_deleted,
                files_deleted=files,
                file_outcomes=file_outcomes,
                block=block,
            )
