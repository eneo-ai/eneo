"""Discovery and the fresh policy check for the two conversation root stores.

The bounded removal of each root is the shared conversation unit's.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from eneo.data_retention.application.conversation_retention import (
    ConversationDeletion,
    ConversationPage,
    ConversationRootKind,
    ConversationUnitResult,
    is_past_owner,
    past_owner,
)
from eneo.data_retention.application.retention_runner import RetentionContractError
from eneo.data_retention.domain.retention import (
    RetentionKeyset,
    RetentionOverdue,
)
from eneo.data_retention.infrastructure.conversation_retention_policy import (
    conversation_retention_policy,
)
from eneo.data_retention.infrastructure.conversation_unit_repo import (
    ConversationUnitRepository,
)
from eneo.data_retention.infrastructure.retention_sql import (
    question_in_widget,
    uuid_in,
)
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.spaces_table import Spaces
from eneo.policy_levels import PolicyLevel


class ConversationRetentionRepository:
    def __init__(
        self, session: AsyncSession, *, kind: ConversationRootKind, now: datetime
    ) -> None:
        self.session = session
        self.kind = kind
        self.examined_key = "owners_examined"
        self.now = now
        self.unit = ConversationUnitRepository(session, kind=kind, now=now)
        self.records: type[Questions] | type[AppRuns]
        self.owner: type[Assistants] | type[Apps]
        self.owner_fk: ColumnElement[UUID] | ColumnElement[UUID | None]
        # A widget conversation's root, which only widget retention removes.
        # The fresh check inside the delete refuses it; discovery and the
        # overdue walk read it in their bounded window and pass it, so a
        # widget backlog inside an owner's period is never one unbounded read.
        self.widget_root: ColumnElement[bool]
        if kind is ConversationRootKind.QUESTION:
            self.records = Questions
            self.owner = Assistants
            self.owner_fk = Questions.assistant_id.expression
            self.widget_root = question_in_widget()
        else:
            self.records = AppRuns
            self.owner = Apps
            self.owner_fk = AppRuns.app_id.expression
            # App runs have no session, so no widget conversation.
            self.widget_root = sa.false()
        self.policy = conversation_retention_policy(
            self.owner.data_retention_days.expression
        )
        self.cutoff = self.now - sa.func.make_interval(0, 0, 0, self.policy.days)

    def _due(self) -> sa.Select[tuple[UUID, datetime, UUID, str | None]]:
        return (
            sa.select(
                self.records.id,
                self.records.created_at,
                self.owner.id.label("owner_id"),
                self.policy.source.label("policy_source"),
            )
            .join(self.owner, self.owner_fk == self.owner.id)
            .join(Spaces, self.owner.space_id == Spaces.id)
            .outerjoin(
                AuditRetentionPolicy, Spaces.tenant_id == AuditRetentionPolicy.tenant_id
            )
            .where(
                self.policy.days.is_not(None),
                self.records.created_at < self.cutoff,
                ~self.widget_root,
            )
        )

    def _owners(
        self, overdue_window: timedelta = timedelta(0)
    ) -> sa.Select[tuple[UUID, datetime, int | None]]:
        """Owners with an effective policy, and the cutoff each one applies."""
        return (
            sa.select(
                self.owner.id,
                (self.cutoff - overdue_window).label("cutoff"),
                self.policy.days.label("days"),
            )
            .join(Spaces, self.owner.space_id == Spaces.id)
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
        query = sa.select(self.owner.id)
        if cursor is not None:
            if cursor.group is None:
                raise RetentionContractError(
                    "A conversation keyset must identify its owner."
                )
            query = query.where(
                self.owner.id > cursor.group
                if is_past_owner(cursor)
                else self.owner.id >= cursor.group
            )
        return tuple(
            await self.session.scalars(query.order_by(self.owner.id).limit(limit))
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
                uuid_in(self.owner.id, owner_ids),
                self.owner.id.between(min(owner_ids), max(owner_ids)),
            )
            .order_by(self.owner.id)
            .subquery("conversation_owners")
        )
        due = sa.select(
            self.records.id,
            self.records.created_at,
            (
                self.records.created_at + sa.func.make_interval(0, 0, 0, owners.c.days)
            ).label("due_at"),
            self.widget_root.label("passed"),
        ).where(
            self.owner_fk == owners.c.id,
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
                roots.c.passed,
            )
            .select_from(owners.join(roots, sa.true()))
            .order_by(owners.c.id, roots.c.created_at, roots.c.id)
            .limit(limit)
            .cte("conversation_window")
            .prefix_with("MATERIALIZED")
        )

    def _lock_statement(
        self, owner_ids: Sequence[UUID], cursor: RetentionKeyset | None, limit: int
    ) -> sa.Select[tuple[UUID, datetime, UUID, UUID | None, bool]]:
        window = self._window_statement(owner_ids, cursor, limit)
        locked = (
            sa.select(self.records.id.label("locked_id"))
            .where(self.records.id == window.c.id, ~window.c.passed)
            .with_for_update(of=self.records, skip_locked=True)
            .correlate(window)
            .lateral("locked_conversation")
        )
        return (
            sa.select(
                window.c.id,
                window.c.created_at,
                window.c.owner_id,
                locked.c.locked_id,
                window.c.passed,
            )
            .select_from(window.outerjoin(locked, sa.true()))
            .order_by(window.c.owner_id, window.c.created_at, window.c.id)
        )

    async def overdue(
        self, *, window: timedelta, limit: int, owner_page: int, max_pages: int
    ) -> RetentionOverdue:
        """Due work past `window` over every owner, up to `limit` rows.

        Pages of `owner_page` owners and at most `limit + 1` roots, each
        statement bounded, until the owners end or `limit + 1` rows are found.
        The page does not follow `limit`, so a small remaining cap does not
        cost two statements per owner. A page whose roots fill it (widget
        roots, which are read and passed, included) continues after its last
        root. This reads up to `max_pages` pages once per execution, in its own
        transaction outside the budget, and reports the snapshot incomplete
        when roots or owners are left after them: the walk runs after the
        execution's deadline, so its time is bounded by statements, not by the
        budget.
        """
        found: list[datetime] = []
        cursor: RetentionKeyset | None = None
        for _page in range(max_pages):
            owner_ids = await self._owner_page(cursor, owner_page)
            roots: Sequence[tuple[UUID, datetime, UUID, datetime, bool]] = []
            if owner_ids:
                candidates = self._window_statement(
                    owner_ids, cursor, limit + 1, window
                )
                roots = (
                    (
                        await self.session.execute(
                            sa.select(
                                candidates.c.id,
                                candidates.c.created_at,
                                candidates.c.owner_id,
                                sa.type_coerce(
                                    candidates.c.due_at, sa.DateTime(timezone=True)
                                ),
                                candidates.c.passed,
                            ).order_by(
                                candidates.c.owner_id,
                                candidates.c.created_at,
                                candidates.c.id,
                            )
                        )
                    )
                    .tuples()
                    .all()
                )
                found.extend(due_at for *_, due_at, passed in roots if not passed)
            full = len(roots) > limit
            if len(found) > limit or (not full and len(owner_ids) < owner_page):
                complete = len(found) <= limit
                break
            if full:
                identifier, at, owner, *_ = roots[-1]
                cursor = RetentionKeyset(at=at, id=identifier, group=owner)
            else:
                cursor = past_owner(owner_ids[-1])
        else:
            complete = False
        covered = found[:limit]
        return RetentionOverdue(
            count=len(covered),
            complete=complete,
            oldest_due_at=min(covered) if covered else None,
        )

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage:
        owner_ids = await self._owner_page(cursor, limit)
        if not owner_ids:
            return ConversationPage(
                roots=(), locked_ids=(), examined=0, done=None, complete=True
            )
        rows = (
            (await self.session.execute(self._lock_statement(owner_ids, cursor, limit)))
            .tuples()
            .all()
        )
        return ConversationPage(
            roots=tuple(
                RetentionKeyset(at=at, id=identifier, group=owner)
                for identifier, at, owner, _locked, _passed in rows
            ),
            locked_ids=tuple(
                locked for *_, locked, _passed in rows if locked is not None
            ),
            examined=len(owner_ids),
            done=past_owner(owner_ids[-1]),
            complete=len(owner_ids) < limit,
            passed_ids=tuple(identifier for identifier, *_, passed in rows if passed),
        )

    async def delete_if_still_due(
        self, identifier: UUID
    ) -> ConversationDeletion | None:
        # Re-read policy in the DELETE snapshot, after discovery and proof.
        fresh = (
            self._due()
            .where(self.records.id == identifier)
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
        row = (await self.session.execute(statement)).tuples().one_or_none()
        if row is None:
            return None
        deleted_id, tenant_id, source = row
        return ConversationDeletion(
            id=deleted_id,
            tenant_id=tenant_id,
            source=PolicyLevel(source),
        )

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
            delete=self.delete_if_still_due,
            child_rows=child_rows,
            max_rows=max_rows,
            max_files=max_files,
            max_family_rows=max_family_rows,
        )
