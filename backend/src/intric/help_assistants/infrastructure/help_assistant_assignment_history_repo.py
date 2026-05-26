"""Async SQLAlchemy repository for ``help_assistant_assignment_history``.

Append-only audit data. Exposes read helpers plus a single ``add()`` — no
``update()`` or ``delete()``. Rows change only when the FK
``assistant_id`` / ``replaced_by_assistant_id`` is set to NULL via
``ON DELETE SET NULL`` once an assistant is archived (PRD §3, §9).
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa

from intric.database.database import AsyncSession
from intric.database.tables.help_assistant_assignment_history_table import (
    HelpAssistantAssignmentHistory,
)
from intric.help_assistants.domain.assignment_history import AssignmentHistory
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.factory import HelperAssistantsFactory
from intric.help_assistants.domain.helper_kind import HelperKind


class HelpAssistantAssignmentHistoryRepo:
    def __init__(self, session: AsyncSession, factory: HelperAssistantsFactory) -> None:
        self.session = session
        self.factory = factory

    def _to_domain(
        self, row: HelpAssistantAssignmentHistory | None
    ) -> AssignmentHistory | None:
        if row is None:
            return None

        return self.factory.create_assignment_history_entry(
            id=row.id,
            org_space_id=row.org_space_id,
            kind=HelperKind(row.kind),
            assistant_id=row.assistant_id,
            assistant_name_snapshot=row.assistant_name_snapshot,
            replaced_by_assistant_id=row.replaced_by_assistant_id,
            reason=AssignmentHistoryReason(row.reason),
            actor_user_id=row.actor_user_id,
            replaced_at=row.replaced_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, entry: AssignmentHistory) -> AssignmentHistory:
        values: dict[str, object] = {
            "org_space_id": entry.org_space_id,
            "kind": entry.kind.value,
            "assistant_id": entry.assistant_id,
            "assistant_name_snapshot": entry.assistant_name_snapshot,
            "replaced_by_assistant_id": entry.replaced_by_assistant_id,
            "reason": entry.reason.value,
            "actor_user_id": entry.actor_user_id,
        }
        if entry.replaced_at is not None:
            values["replaced_at"] = entry.replaced_at

        stmt = (
            sa.insert(HelpAssistantAssignmentHistory)
            .values(**values)
            .returning(HelpAssistantAssignmentHistory)
        )
        row = await self.session.scalar(stmt)
        assert row is not None
        result = self._to_domain(row)
        assert result is not None
        return result

    async def list_by_org_space_and_kind(
        self, org_space_id: UUID, kind: HelperKind
    ) -> list[AssignmentHistory]:
        stmt = (
            sa.select(HelpAssistantAssignmentHistory)
            .where(
                HelpAssistantAssignmentHistory.org_space_id == org_space_id,
                HelpAssistantAssignmentHistory.kind == kind.value,
            )
            .order_by(HelpAssistantAssignmentHistory.replaced_at.desc())
        )
        result = await self.session.scalars(stmt)
        return [entry for row in result if (entry := self._to_domain(row)) is not None]

    async def list_replaced_assistant_ids_by_org_space(
        self, org_space_id: UUID
    ) -> set[UUID]:
        stmt = sa.select(HelpAssistantAssignmentHistory.assistant_id).where(
            HelpAssistantAssignmentHistory.org_space_id == org_space_id,
            HelpAssistantAssignmentHistory.assistant_id.is_not(None),
        )
        result = await self.session.scalars(stmt)
        return {row for row in result if row is not None}

    async def exists_for_assistant(self, assistant_id: UUID) -> bool:
        stmt = sa.select(
            sa.exists().where(
                sa.or_(
                    HelpAssistantAssignmentHistory.assistant_id == assistant_id,
                    HelpAssistantAssignmentHistory.replaced_by_assistant_id
                    == assistant_id,
                )
            )
        )
        result = await self.session.scalar(stmt)
        return bool(result)
