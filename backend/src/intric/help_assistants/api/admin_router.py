"""Admin router for help-assistant role management (PRD §5, §9).

Tenant-ADMIN-gated HTTP surface for ``OrgSpaceAssistantRoleService``:
list / get / assign / unassign / toggle (enabled, visible_to_users) /
reset (instructions-only, full) / list history / list and archive replaced
helpers. Mutations are audit-logged inside the service layer; the FastAPI
``audit_service`` reads ``ip_address`` / ``user_agent`` / ``request_id``
from the ``RequestContextMiddleware`` contextvars, so the router does not
need to thread request metadata explicitly (same as ``assistant_router``).

Permission enforcement is owned by the service (every mutation calls
``validate_permission(self.user, Permission.ADMIN)`` and raises
``UnauthorizedException`` → 403); ``get_active`` is exposed here for admin
diagnostics even though it is admin-free at the service layer because the
prompt-guide modal also calls it for every signed-in user via the
availability endpoint (step 023).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

if TYPE_CHECKING:
    from intric.assistants.assistant_service import AssistantService

from intric.help_assistants.api.admin_models import (
    AssignmentHistoryPublic,
    AssistantSummaryPublic,
    RoleAssignmentPublic,
    ToggleRequest,
)
from intric.help_assistants.domain.assignment_history import AssignmentHistory
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.role_assignment import RoleAssignment
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

router = APIRouter()

AdminContainer = Annotated[Container, Depends(get_container(with_user=True))]


def _role_to_public(
    role: RoleAssignment, assistant_name: str | None = None
) -> RoleAssignmentPublic:
    assert role.id is not None
    assert role.created_at is not None
    assert role.updated_at is not None
    return RoleAssignmentPublic(
        id=role.id,
        org_space_id=role.org_space_id,
        kind=role.kind,
        assistant_id=role.assistant_id,
        assistant_name=assistant_name,
        is_enabled=role.is_enabled,
        is_visible_to_users=role.is_visible_to_users,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


async def _resolve_name(
    assistant_service: "AssistantService", role: RoleAssignment
) -> str | None:
    """Display name of the assistant filling ``role`` (for the admin table).

    An active role always points at a live org-space assistant the caller can
    read — the helper-run path loads the same assistant as an ordinary user,
    so an admin load is strictly more privileged. Returned only on the read
    endpoints; mutations leave ``assistant_name`` ``None`` (the UI re-fetches).
    """
    assistant, _permissions = await assistant_service.get_assistant(
        assistant_id=role.assistant_id
    )
    return assistant.name


def _history_to_public(entry: AssignmentHistory) -> AssignmentHistoryPublic:
    assert entry.id is not None
    assert entry.replaced_at is not None
    return AssignmentHistoryPublic(
        id=entry.id,
        org_space_id=entry.org_space_id,
        kind=entry.kind,
        assistant_id=entry.assistant_id,
        assistant_name_snapshot=entry.assistant_name_snapshot,
        replaced_by_assistant_id=entry.replaced_by_assistant_id,
        reason=entry.reason,
        actor_user_id=entry.actor_user_id,
        replaced_at=entry.replaced_at,
    )


@router.get(
    "/roles/",
    response_model=PaginatedResponse[RoleAssignmentPublic],
)
async def list_roles(container: AdminContainer):
    service = container.org_space_assistant_role_service()
    assistant_service = container.assistant_service()
    roles = await service.list_for_calling_tenant()
    items = [
        _role_to_public(
            role, assistant_name=await _resolve_name(assistant_service, role)
        )
        for role in roles
    ]
    return protocol.to_paginated_response(items)


@router.get(
    "/roles/{kind}/",
    response_model=RoleAssignmentPublic | None,
    responses=responses.get_responses([404]),
)
async def get_active_role(kind: HelperKind, container: AdminContainer):
    service = container.org_space_assistant_role_service()
    role = await service.get_active(kind=kind)
    if role is None:
        return None
    assistant_service = container.assistant_service()
    return _role_to_public(
        role, assistant_name=await _resolve_name(assistant_service, role)
    )


@router.patch(
    "/roles/{kind}/enabled",
    response_model=RoleAssignmentPublic,
    responses=responses.get_responses([400, 403]),
)
async def toggle_enabled(
    kind: HelperKind,
    body: ToggleRequest,
    container: AdminContainer,
):
    service = container.org_space_assistant_role_service()
    role = await service.toggle_enabled(kind=kind, value=body.value)
    return _role_to_public(role)


@router.patch(
    "/roles/{kind}/visible",
    response_model=RoleAssignmentPublic,
    responses=responses.get_responses([400, 403]),
)
async def toggle_visible(
    kind: HelperKind,
    body: ToggleRequest,
    container: AdminContainer,
):
    service = container.org_space_assistant_role_service()
    role = await service.toggle_visible_to_users(kind=kind, value=body.value)
    return _role_to_public(role)


@router.post(
    "/roles/{kind}/reset-instructions",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=responses.get_responses([400, 403]),
)
async def reset_instructions(kind: HelperKind, container: AdminContainer):
    service = container.org_space_assistant_role_service()
    await service.reset_instructions_only(kind=kind)


@router.post(
    "/roles/{kind}/reset-to-default",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=responses.get_responses([400, 403]),
)
async def reset_to_default(kind: HelperKind, container: AdminContainer):
    service = container.org_space_assistant_role_service()
    await service.reset_to_default(kind=kind)


@router.get(
    "/roles/{kind}/history",
    response_model=PaginatedResponse[AssignmentHistoryPublic],
    responses=responses.get_responses([403]),
)
async def list_history(kind: HelperKind, container: AdminContainer):
    service = container.org_space_assistant_role_service()
    entries = await service.list_history(kind=kind)
    return protocol.to_paginated_response([_history_to_public(e) for e in entries])


@router.get(
    "/roles/{kind}/archivable",
    response_model=PaginatedResponse[AssistantSummaryPublic],
    responses=responses.get_responses([403]),
)
async def list_archivable(kind: HelperKind, container: AdminContainer):
    service = container.org_space_assistant_role_service()
    assistants = await service.list_archivable_helpers(kind=kind)
    summaries = [AssistantSummaryPublic(id=a.id, name=a.name) for a in assistants]
    return protocol.to_paginated_response(summaries)


@router.post(
    "/roles/{kind}/archive/{assistant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=responses.get_responses([400, 403]),
)
async def archive_helper(
    kind: HelperKind,  # noqa: ARG001 — kept for URL symmetry with the other admin routes
    assistant_id: UUID,
    container: AdminContainer,
):
    service = container.org_space_assistant_role_service()
    await service.archive_helper(assistant_id=assistant_id)
