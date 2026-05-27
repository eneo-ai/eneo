"""Pydantic models for the help-assistant admin router (PRD §5, §9).

Public shapes returned by ``/api/v1/admin/help-assistants/...`` plus the
request bodies for the few mutating endpoints. ``RoleAssignmentPublic``
mirrors ``org_space_assistant_roles``; ``AssignmentHistoryPublic`` mirrors
``help_assistant_assignment_history`` (PRD §3). ``AssistantSummaryPublic``
is the minimal shape the admin UI needs to render the archivable-helpers
list — full ``AssistantPublic`` would pull in fields the admin doesn't
use here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.helper_kind import HelperKind


class RoleAssignmentPublic(BaseModel):
    """One row of ``org_space_assistant_roles``.

    ``assistant_name`` is a display convenience for the admin table: it is
    resolved (via the assistant load) only on the read endpoints
    (``list_roles`` / ``get_active_role``) the UI renders from. Mutation
    responses leave it ``None`` because the admin page re-fetches the list
    after every mutation, so the displayed name always comes from a read.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_space_id: UUID
    kind: HelperKind
    assistant_id: UUID
    assistant_name: str | None = None
    is_enabled: bool
    is_visible_to_users: bool
    created_at: datetime
    updated_at: datetime


class AssignmentHistoryPublic(BaseModel):
    """One row of ``help_assistant_assignment_history`` (PRD §3)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_space_id: UUID
    kind: HelperKind
    assistant_id: UUID | None
    assistant_name_snapshot: str
    replaced_by_assistant_id: UUID | None
    reason: AssignmentHistoryReason
    actor_user_id: UUID | None
    replaced_at: datetime


class AssistantSummaryPublic(BaseModel):
    """Minimal assistant shape for the archivable-helpers list."""

    id: UUID
    name: str


class ToggleRequest(BaseModel):
    value: bool
