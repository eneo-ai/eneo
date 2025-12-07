# MIT License

from uuid import UUID

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.roles.role import (
    PermissionPublic,
    RoleCreateRequest,
    RolePublic,
    RolesPaginatedResponse,
    RoleUpdateRequest,
)
from intric.roles.roles_protocol import to_roles_paginated_response
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

router = APIRouter()


@router.get(
    "/permissions/",
    response_model=list[PermissionPublic],
    responses=responses.get_responses([404]),
)
async def get_permissions(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    return await service.get_permissions()


@router.get(
    "/",
    response_model=RolesPaginatedResponse,
)
async def get_roles(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    predefined_roles_service = container.predefined_role_service()

    roles = await service.get_all_roles()
    predefined_roles = await predefined_roles_service.get_predefined_roles()

    return to_roles_paginated_response(roles=roles, predefined_roles=predefined_roles)


@router.get(
    "/{role_id}/",
    response_model=RolePublic,
    responses=responses.get_responses([404]),
)
async def get_role_by_id(
    role_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    return await service.get_role_by_uuid(role_id)


@router.post("/", response_model=RolePublic)
async def create_role(
    role: RoleCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    user = container.user()

    # Create role
    created_role = await service.create_role(role)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
    response_model=RolePublic,
    responses=responses.get_responses([404]),
)
async def update_role(
    role_id: UUID,
    role: RoleUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    user = container.user()

    # Get old role for tracking changes
    old_role = await service.get_role_by_uuid(role_id)

    # Update role
    updated_role = await service.update_role(role_id=role_id, role_update=role)

    # Track changes
    changes = {}
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
        actor_id=user.id,
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
    response_model=RolePublic,
    responses=responses.get_responses([404]),
)
async def delete_role_by_id(
    role_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.role_service()
    user = container.user()

    # Get role info before deletion (snapshot pattern)
    role_to_delete = await service.get_role_by_uuid(role_id)

    # Delete role
    deleted_role = await service.delete_role(role_id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
