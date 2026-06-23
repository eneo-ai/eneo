"""``HelperRun`` domain entity.

Represents one row of ``help_assistant_runs`` — the canonical record of a
single Help-Assistant invocation. One-to-one with a ``sessions`` row.
``tenant_id`` is explicit (PRD §6) because every list/read of this table,
and every retention sweep, hits it on the hot path.

Status transitions are owned by the application/repository layer
(``HelperRunService.set_status`` → a conditional UPDATE), not by the entity,
so terminal moves stay atomic against concurrent requests.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from intric.base.base_entity import Entity
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.helper_run_status import HelperRunStatus


class HelperRun(Entity):
    def __init__(
        self,
        id: UUID | None,
        tenant_id: UUID,
        org_space_id: UUID,
        kind: HelperKind,
        assistant_id: UUID | None,
        target_type: str,
        target_id: UUID,
        session_id: UUID,
        actor_user_id: UUID | None,
        status: HelperRunStatus = HelperRunStatus.IN_PROGRESS,
        completed_at: datetime | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)

        self.tenant_id = tenant_id
        self.org_space_id = org_space_id
        self.kind = kind
        self.assistant_id = assistant_id
        self.target_type = target_type
        self.target_id = target_id
        self.session_id = session_id
        self.actor_user_id = actor_user_id
        self.status = status
        self.completed_at = completed_at
