"""Admin router for help-assistant role management (PRD §5, §9).

Tenant-ADMIN-gated HTTP surface for ``OrgSpaceAssistantRoleService``:
list installed roles / get one / toggle (enabled, visible_to_users) /
list installable templates / install a template / uninstall a helper.
Mutations are audit-logged inside the service layer; the FastAPI
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

from fastapi import APIRouter, Depends, status

if TYPE_CHECKING:
    from eneo.assistants.assistant_service import AssistantService

from eneo.help_assistants.api.admin_models import (
    HelperTemplatePublic,
    RoleAssignmentPublic,
    ToggleRequest,
)
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.role_assignment import RoleAssignment
from eneo.main.container.container import Container
from eneo.main.models import PaginatedResponse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

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


@router.get(
    "/roles/",
    response_model=PaginatedResponse[RoleAssignmentPublic],
    description="List the Help-Assistant roles installed for the calling tenant.",
    responses=responses.get_responses([403]),
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
    "/templates/",
    response_model=PaginatedResponse[HelperTemplatePublic],
    responses=responses.get_responses([403]),
)
async def list_templates(container: AdminContainer):
    """Shipped Help Assistant templates not yet installed for the tenant."""
    service = container.org_space_assistant_role_service()
    available = await service.list_available_templates()
    items = [
        HelperTemplatePublic(
            kind=kind, name=template.name, description=template.description
        )
        for kind, template in available
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


@router.post(
    "/roles/{kind}/",
    response_model=RoleAssignmentPublic,
    status_code=status.HTTP_201_CREATED,
    description="Install a shipped Help-Assistant template (blank helper + active role).",
    responses=responses.get_responses([400, 403]),
)
async def install_helper(kind: HelperKind, container: AdminContainer):
    """Install a shipped template; creates a blank helper + active role."""
    service = container.org_space_assistant_role_service()
    role = await service.install_helper(kind=kind)
    return _role_to_public(role)


@router.delete(
    "/roles/{kind}/",
    status_code=204,
    description="Uninstall the active helper for a kind (deletes its role and assistant).",
    responses=responses.get_responses([400, 403]),
)
async def uninstall_helper(kind: HelperKind, container: AdminContainer):
    """Uninstall the active helper for ``kind`` (role + assistant)."""
    service = container.org_space_assistant_role_service()
    await service.uninstall_helper(kind=kind)


@router.patch(
    "/roles/{kind}/enabled",
    response_model=RoleAssignmentPublic,
    description="Enable or disable a helper role for the tenant.",
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
    description="Show or hide a helper role from end users.",
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
