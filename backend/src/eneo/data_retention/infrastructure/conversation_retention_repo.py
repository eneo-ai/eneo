"""Locked pages and fresh deletes for the two conversation root stores."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import count
from sqlalchemy.sql.selectable import CTE

from eneo.data_retention.application.conversation_retention import (
    ConversationDeletion,
    ConversationPage,
)
from eneo.data_retention.application.retention_runner import RetentionContractError
from eneo.data_retention.domain.retention import (
    ConversationPolicySource,
    RetentionKeyset,
    RetentionOverdue,
)
from eneo.data_retention.infrastructure.conversation_retention_policy import (
    conversation_retention_policy,
)
from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_retention_policy_table import AuditRetentionPolicy
from eneo.database.tables.mcp_tool_references_table import McpToolReference
from eneo.database.tables.questions_table import (
    InfoBlobReferences,
    Questions,
    QuestionsFiles,
)
from eneo.database.tables.spaces_table import Spaces


class ConversationRootKind(StrEnum):
    QUESTION = "question"
    APP_RUN = "app_run"


class ConversationRetentionRepository:
    def __init__(
        self, session: AsyncSession, *, kind: ConversationRootKind, now: datetime
    ) -> None:
        self.session = session
        self.now = now
        self.records: type[Questions] | type[AppRuns]
        self.parent: type[Assistants] | type[Apps]
        self.parent_fk: ColumnElement[UUID] | ColumnElement[UUID | None]
        self.children: tuple[ColumnElement[UUID], ...]
        if kind is ConversationRootKind.QUESTION:
            self.records = Questions
            self.parent = Assistants
            self.parent_fk = Questions.assistant_id.expression
            self.children = (
                InfoBlobReferences.question_id.expression,
                QuestionsFiles.question_id.expression,
                McpToolReference.question_id.expression,
            )
        else:
            self.records = AppRuns
            self.parent = Apps
            self.parent_fk = AppRuns.app_id.expression
            self.children = (AppRunsFiles.app_run_id.expression,)
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

    def _window_statement(
        self,
        cursor: RetentionKeyset | None,
        limit: int,
        overdue_window: timedelta = timedelta(0),
    ) -> CTE:
        owners_query = (
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
        if cursor is not None:
            if cursor.group is None:
                raise RetentionContractError(
                    "A conversation keyset must identify its owner."
                )
            owners_query = owners_query.where(self.parent.id >= cursor.group)
        owners = owners_query.order_by(self.parent.id).subquery("conversation_owners")
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
        if cursor is not None:
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
        self, cursor: RetentionKeyset | None, limit: int
    ) -> sa.Select[tuple[UUID, datetime, UUID, UUID | None]]:
        window = self._window_statement(cursor, limit)
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

    async def overdue(self, *, window: timedelta, limit: int) -> RetentionOverdue:
        candidates = self._window_statement(None, limit + 1, window)
        deadline = sa.type_coerce(candidates.c.due_at, sa.DateTime(timezone=True))
        rows = (
            await self.session.scalars(
                sa.select(deadline).order_by(
                    candidates.c.owner_id,
                    candidates.c.created_at,
                    candidates.c.id,
                )
            )
        ).all()
        covered = rows[:limit]
        return RetentionOverdue(
            count=len(covered),
            complete=len(rows) <= limit,
            oldest_due_at=min(covered) if covered else None,
        )

    async def lock_due_page(
        self, cursor: RetentionKeyset | None, limit: int
    ) -> ConversationPage:
        rows = (
            (await self.session.execute(self._lock_statement(cursor, limit)))
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
        )

    def _capped_child_count(
        self, foreign_key: ColumnElement[UUID], ceiling: int
    ) -> ColumnElement[int]:
        children = (
            sa.select(foreign_key)
            .where(foreign_key == self.records.id)
            .limit(ceiling + 1)
            .correlate(self.records)
            .subquery()
        )
        return sa.select(count()).select_from(children).scalar_subquery()

    async def cascade_costs(
        self, ids: Sequence[UUID], ceiling: int
    ) -> Mapping[UUID, int]:
        cost: ColumnElement[int] = sa.literal(0)
        for foreign_key in self.children:
            cost = cost + self._capped_child_count(foreign_key, ceiling)
        statement = sa.select(self.records.id, cost).where(
            uuid_in(self.records.id, ids)
        )
        rows = (await self.session.execute(statement)).tuples().all()
        return dict(rows)

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
