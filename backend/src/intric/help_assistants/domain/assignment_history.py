"""``AssignmentHistory`` domain entity.

Represents one row of ``help_assistant_assignment_history`` — an append-only
audit trail entry written when the assistant filling a role slot is reset,
reassigned, or unassigned. ``assistant_name_snapshot`` preserves identity
after the underlying assistant row may have been archived (FK is
``ON DELETE SET NULL`` per PRD §3).

Pure Python: no DB calls, no service dependencies.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from intric.base.base_entity import Entity
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.helper_kind import HelperKind


class AssignmentHistory(Entity):
    def __init__(
        self,
        id: UUID | None,
        org_space_id: UUID,
        kind: HelperKind,
        assistant_id: UUID | None,
        assistant_name_snapshot: str,
        replaced_by_assistant_id: UUID | None,
        reason: AssignmentHistoryReason,
        actor_user_id: UUID | None,
        replaced_at: datetime | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)

        self.org_space_id = org_space_id
        self.kind = kind
        self.assistant_id = assistant_id
        self.assistant_name_snapshot = assistant_name_snapshot
        self.replaced_by_assistant_id = replaced_by_assistant_id
        self.reason = reason
        self.actor_user_id = actor_user_id
        self.replaced_at = replaced_at
