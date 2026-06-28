# MIT License

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import (
    require_permission,
    require_user_for_creation,
)
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.roles.role import (
    PermissionPublic,
    RoleCreateRequest,
    RoleInDB,
    RolePublic,
    RolesPaginatedResponse,
    RoleUpdateRequest,
)
from eneo.roles.roles_protocol import to_roles_paginated_response
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenants.tenant import TenantUpdatePublic

router = APIRouter()

_ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]


@router.get(
    "/permissions/",
    response_model=list[PermissionPublic],
    responses=responses.get_responses([404]),
)
async def get_permissions(
    container: _ContainerDep,
) -> list[PermissionPublic]:
    service = container.role_service()
    return await service.get_permissions()


@router.get(
    "/templates/",
    description="List the predefined role templates available for creating roles.",
    responses=responses.get_responses([]),
    response_model=None,
)
async def get_role_templates(
    container: Container = Depends(get_container(with_user=True)),
):
    from eneo.server.dependencies.predefined_roles import (
        load_predefined_roles_from_config,
    )

    return load_predefined_roles_from_config()


@router.get(
    "/",
    description="List all roles for the current tenant.",
    response_model=RolesPaginatedResponse,
    responses=responses.get_responses([403]),
)
async def get_roles(
    container: _ContainerDep,
) -> RolesPaginatedResponse:
    service = container.role_service()
    roles = await service.get_all_roles()

    return to_roles_paginated_response(roles=roles)


@router.get(
    "/{role_id}/",
    response_model=RolePublic,
    responses=responses.get_responses([403, 404]),
)
async def get_role_by_id(
    role_id: UUID,
    container: _ContainerDep,
) -> RoleInDB | None:
    service = container.role_service()
    return await service.get_role_by_uuid(role_id)


@router.post(
    "/",
    description="Create a new role for the current tenant.",
    response_model=RolePublic,
    responses=responses.get_responses([400, 403]),
)
async def create_role(
    role: RoleCreateRequest,
    container: _ContainerDep,
    _user_for_creation: None = Depends(require_user_for_creation),
) -> RoleInDB:
    service = container.role_service()
    user = container.user()

    # Create role
    created_role = await service.create_role(role)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ROLE_CREATED,
        entity_type=EntityType.ROLE,
        entity_id=created_role.id,
        description=f"Created role '{created_role.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=created_role,
            extra={"permissions": [str(p) for p in created_role.permissions]},
        ),
    )

    return created_role


@router.post(
    "/{role_id}/",
    description="Update an existing role by id.",
    response_model=RolePublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_role(
    role_id: UUID,
    role: RoleUpdateRequest,
    container: _ContainerDep,
) -> RoleInDB | None:
    service = container.role_service()
    user = container.user()

    # Get old role for tracking changes
    old_role = await service.get_role_by_uuid(role_id)

    # Update role
    updated_role = await service.update_role(role_id=role_id, role_update=role)
    assert updated_role is not None

    # Track changes
    changes: dict[str, dict[str, object]] = {}
    if role.name and role.name != old_role.name:
        changes["name"] = {"old": old_role.name, "new": role.name}
    if role.permissions and set(role.permissions) != set(old_role.permissions):
        changes["permissions"] = {
            "old": [str(p) for p in old_role.permissions],
            "new": [str(p) for p in role.permissions],
        }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ROLE_MODIFIED,
        entity_type=EntityType.ROLE,
        entity_id=role_id,
        description=f"Updated role '{updated_role.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=updated_role,
            changes=changes,
        ),
    )

    return updated_role


@router.delete(
    "/{role_id}/",
    description="Delete a role by id.",
    response_model=RolePublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def delete_role_by_id(
    role_id: UUID,
    container: _ContainerDep,
) -> RoleInDB | None:
    service = container.role_service()
    user = container.user()

    # Get role info before deletion (snapshot pattern)
    role_to_delete = await service.get_role_by_uuid(role_id)
    assert role_to_delete is not None

    # Delete role
    deleted_role = await service.delete_role(role_id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ROLE_DELETED,
        entity_type=EntityType.ROLE,
        entity_id=role_id,
        description=f"Deleted role '{role_to_delete.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=role_to_delete,
            extra={"permissions": [str(p) for p in role_to_delete.permissions]},
        ),
    )

    return deleted_role


@router.post(
    "/{role_id}/reset/",
    description="Reset a role's permissions to its default template.",
    response_model=RolePublic,
    responses=responses.get_responses([400, 403, 404]),
)
async def reset_role_to_default(
    role_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    user = container.user()

    # Get old role for tracking changes
    old_role = await service.get_role_by_uuid(role_id)

    # Reset role
    reset_role = await service.reset_role_to_default(role_id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ROLE_MODIFIED,
        entity_type=EntityType.ROLE,
        entity_id=role_id,
        description=f"Reset role '{old_role.name}' to default",
        metadata=AuditMetadata.standard(
            actor=user,
            target=reset_role,
            changes={
                "permissions": {
                    "old": [str(p) for p in old_role.permissions],
                    "new": [str(p) for p in reset_role.permissions],
                }
            },
        ),
    )

    return reset_role


@router.post(
    "/{role_id}/set-default/",
    description="Set the given role as the tenant's default role.",
    response_model=RolePublic,
    responses=responses.get_responses([403, 404]),
    dependencies=[Depends(require_permission(Permission.ADMIN))],
)
async def set_default_role(
    role_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    user = container.user()

    # Validate role exists and belongs to tenant
    role = await service.get_role_by_uuid(role_id)

    # Update tenant's default_role_id
    tenant_service = container.tenant_service()
    await tenant_service.update_tenant(
        TenantUpdatePublic(default_role_id=role_id),
        id=user.tenant_id,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.TENANT_SETTINGS_UPDATED,
        entity_type=EntityType.TENANT_SETTINGS,
        entity_id=user.tenant_id,
        description=f"Set default role to '{role.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=role,
        ),
    )

    return role


@router.post(
    "/clear-default/",
    description="Clear the tenant's default role.",
    responses=responses.get_responses([403]),
    response_model=None,
    dependencies=[Depends(require_permission(Permission.ADMIN))],
)
async def clear_default_role(
    container: Container = Depends(get_container(with_user=True)),
):
    user = container.user()

    # Clear tenant's default_role_id
    tenant_service = container.tenant_service()
    await tenant_service.update_tenant(
        TenantUpdatePublic(default_role_id=None),
        id=user.tenant_id,
    )

    return {"success": True}
