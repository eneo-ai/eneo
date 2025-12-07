from uuid import UUID

from fastapi import APIRouter, Depends

from intric.main.container.container import Container
from intric.main.models import ModelId, PaginatedResponse
from intric.modules.module import ModuleBase, ModuleInDB
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.tenants.tenant import TenantInDB
from intric.authentication import auth

# Audit logging - module level imports for consistency
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType

router = APIRouter(dependencies=[Depends(auth.authenticate_super_duper_api_key)])


@router.get("/", response_model=PaginatedResponse[ModuleInDB])
async def get_modules(container: Container = Depends(get_container())):
    module_repo = container.module_repo()
    modules = await module_repo.get_all_modules()

    return protocol.to_paginated_response(modules)


@router.post("/", response_model=ModuleInDB)
async def add_module(
    module: ModuleBase, container: Container = Depends(get_container())
):
    module_repo = container.module_repo()
    # Note: Global module addition is system-level - no tenant-specific audit logging
    return await module_repo.add(module)


@router.post("/{tenant_id}/", response_model=TenantInDB)
async def add_module_to_tenant(
    tenant_id: UUID,
    module_ids: list[ModelId],
    container: Container = Depends(get_container()),
):
    """Value is a list of module `id`'s to add to the `tenant_id`."""
    tenant_service = container.tenant_service()

    # Add modules to tenant
    updated_tenant = await tenant_service.add_modules(
        tenant_id=tenant_id, list_of_module_ids=module_ids
    )

    # Audit logging (sysadmin operation - system actor)
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=tenant_id,
        actor_id=tenant_id,  # System actor
        actor_type=ActorType.SYSTEM,
        action=ActionType.MODULE_ADDED_TO_TENANT,
        entity_type=EntityType.MODULE,
        entity_id=tenant_id,  # Use tenant as entity ID
        description=f"Sysadmin added {len(module_ids)} module(s) to tenant",
        metadata={
            "actor": {"type": "sysadmin", "via": "super_duper_api_key"},
            "target": {
                "tenant_id": str(tenant_id),
                "tenant_name": updated_tenant.name,
                "module_count": len(module_ids),
                "module_ids": [str(m.id) for m in module_ids],
            },
        },
    )

    return updated_tenant
