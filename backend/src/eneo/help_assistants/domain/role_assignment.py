"""``RoleAssignment`` domain entity.

Represents one row of ``org_space_assistant_roles`` — which assistant
currently fills a given Help-Assistant role slot (e.g. ``prompt_guide``)
inside an organization space. Tenant scoping derives from the org-space;
no explicit ``tenant_id`` field per PRD §1.

Pure Python: no DB calls, no service dependencies.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from eneo.base.base_entity import Entity
from eneo.help_assistants.domain.helper_kind import HelperKind


class RoleAssignment(Entity):
    def __init__(
        self,
        id: UUID | None,
        org_space_id: UUID,
        kind: HelperKind,
        assistant_id: UUID,
        is_enabled: bool = True,
        is_visible_to_users: bool = True,
        created_by_user_id: UUID | None = None,
        updated_by_user_id: UUID | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)

        self.org_space_id = org_space_id
        self.kind = kind
        self.assistant_id = assistant_id
        self.is_enabled = is_enabled
        self.is_visible_to_users = is_visible_to_users
        self.created_by_user_id = created_by_user_id
        self.updated_by_user_id = updated_by_user_id

    def set_enabled(self, value: bool, actor_user_id: UUID | None) -> None:
        self.is_enabled = value
        self.updated_by_user_id = actor_user_id

    def set_visible_to_users(self, value: bool, actor_user_id: UUID | None) -> None:
        self.is_visible_to_users = value
        self.updated_by_user_id = actor_user_id
