"""Async SQLAlchemy repository for ``help_assistant_runs``.

Tenant-scoped: every read takes a ``tenant_id`` and applies it as a WHERE
clause defensively, even when callers also pass other filters. The table
carries its own ``tenant_id`` column (PRD §6) so the filter is a simple
equality predicate — no join needed, intentionally not shared with
``SessionRepository._filter_by_tenant`` which solves a different problem
(LEFT JOIN through Users / ApiKeysV2).

The lone non-tenant-scoped method is ``is_helper_session``: it answers a
global "is this session id present in the table?" used by step 013's
session-exclusion filter, which already operates inside a tenant-scoped
sessions query.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.help_assistants.domain.factory import HelperAssistantsFactory
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.helper_run import HelperRun
from eneo.help_assistants.domain.helper_run_status import HelperRunStatus


class HelperRunRepo:
    def __init__(self, session: AsyncSession, factory: HelperAssistantsFactory) -> None:
        self.session = session
        self.factory = factory

    @staticmethod
    def _apply_tenant(
        query: sa.Select[tuple[HelpAssistantRuns]], tenant_id: UUID
    ) -> sa.Select[tuple[HelpAssistantRuns]]:
        return query.where(HelpAssistantRuns.tenant_id == tenant_id)

    def _to_domain(self, row: HelpAssistantRuns | None) -> HelperRun | None:
        if row is None:
            return None

        return self.factory.create_helper_run(
            id=row.id,
            tenant_id=row.tenant_id,
            org_space_id=row.org_space_id,
            kind=HelperKind(row.kind),
            assistant_id=row.assistant_id,
            target_type=row.target_type,
            target_id=row.target_id,
            session_id=row.session_id,
            actor_user_id=row.actor_user_id,
            status=HelperRunStatus(row.status),
            completed_at=row.completed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, run: HelperRun) -> HelperRun:
        stmt = (
            sa.insert(HelpAssistantRuns)
            .values(
                tenant_id=run.tenant_id,
                org_space_id=run.org_space_id,
                kind=run.kind.value,
                assistant_id=run.assistant_id,
                target_type=run.target_type,
                target_id=run.target_id,
                session_id=run.session_id,
                actor_user_id=run.actor_user_id,
                status=run.status.value,
                completed_at=run.completed_at,
            )
            .returning(HelpAssistantRuns)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        result = self._to_domain(row)
        assert result is not None
        return result

    async def get_by_id(self, id: UUID, tenant_id: UUID) -> HelperRun | None:
        stmt = self._apply_tenant(
            sa.select(HelpAssistantRuns).where(HelpAssistantRuns.id == id),
            tenant_id,
        )
        return self._to_domain(await self.session.scalar(stmt))

    async def get_by_session_id(
        self, session_id: UUID, tenant_id: UUID
    ) -> HelperRun | None:
        stmt = self._apply_tenant(
            sa.select(HelpAssistantRuns).where(
                HelpAssistantRuns.session_id == session_id
            ),
            tenant_id,
        )
        return self._to_domain(await self.session.scalar(stmt))

    async def update_status(
        self,
        id: UUID,
        tenant_id: UUID,
        status: HelperRunStatus,
        completed_at: datetime | None,
        expected_status: HelperRunStatus | None = None,
    ) -> HelperRun | None:
        """Transition a run's status.

        When ``expected_status`` is given, the UPDATE matches only a row
        still in that status — the WHERE clause is the concurrency guard, so
        two racing terminal transitions cannot both win. Returns ``None``
        when no row matched (already transitioned out of ``expected_status``).
        """
        stmt = (
            sa.update(HelpAssistantRuns)
            .where(
                HelpAssistantRuns.id == id,
                HelpAssistantRuns.tenant_id == tenant_id,
            )
            .values(status=status.value, completed_at=completed_at)
            .returning(HelpAssistantRuns)
        )
        if expected_status is not None:
            stmt = stmt.where(HelpAssistantRuns.status == expected_status.value)
        row = await self.session.scalar(stmt)
        if row is None:
            return None
        result = self._to_domain(row)
        assert result is not None
        return result

    async def list_by_tenant(
        self, tenant_id: UUID, status: HelperRunStatus | None = None
    ) -> list[HelperRun]:
        query = sa.select(HelpAssistantRuns).order_by(
            HelpAssistantRuns.created_at.desc()
        )
        query = self._apply_tenant(query, tenant_id)
        if status is not None:
            query = query.where(HelpAssistantRuns.status == status.value)

        result = await self.session.scalars(query)
        return [run for row in result if (run := self._to_domain(row)) is not None]

    async def delete_older_than(self, tenant_id: UUID, threshold: datetime) -> int:
        stmt = sa.delete(HelpAssistantRuns).where(
            HelpAssistantRuns.tenant_id == tenant_id,
            HelpAssistantRuns.created_at < threshold,
        )
        result = await self.session.execute(stmt)
        return result.rowcount

    async def is_helper_session(self, session_id: UUID) -> bool:
        stmt = sa.select(sa.exists().where(HelpAssistantRuns.session_id == session_id))
        return bool(await self.session.scalar(stmt))
