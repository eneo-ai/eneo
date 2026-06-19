"""Pydantic models for the help-assistant admin router (PRD §5, §9).

Public shapes returned by ``/api/v1/admin/help-assistants/...`` plus the
request bodies for the mutating endpoints. ``RoleAssignmentPublic`` mirrors
``org_space_assistant_roles``; ``HelperTemplatePublic`` is the shape the admin
"Add help assistant" picker renders from (the shipped templates not yet
installed for the tenant).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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


class HelperTemplatePublic(BaseModel):
    """A shipped Help Assistant template available to install.

    Drives the admin "Add help assistant" picker — one entry per shipped
    ``HelperKind`` that is not already installed for the tenant.
    """

    kind: HelperKind
    name: str
    description: str


class ToggleRequest(BaseModel):
    value: bool
