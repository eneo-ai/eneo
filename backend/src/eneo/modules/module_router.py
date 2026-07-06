from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

# Audit logging - module level imports for consistency
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication import auth
from eneo.main.container.container import Container
from eneo.main.models import ModelId, PaginatedResponse
from eneo.modules.module import ModuleBase, ModuleInDB
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenants.tenant import TenantInDB

router = APIRouter(
    dependencies=[Depends(auth.authenticate_super_duper_api_key)],
    responses=responses.get_responses([401]),
)

_Container = Annotated[Container, Depends(get_container())]


@router.get(
    "/",
    response_model=PaginatedResponse[ModuleInDB],
    description="List all globally registered modules.",
    responses=responses.get_responses([]),
)
async def get_modules(
    container: _Container,
) -> PaginatedResponse[ModuleInDB]:
    module_repo = container.module_repo()
    modules = await module_repo.get_all_modules()

    return PaginatedResponse[ModuleInDB](items=modules)


@router.post(
    "/",
    response_model=ModuleInDB,
    description="Register a new global module.",
    responses=responses.get_responses([]),
)
async def add_module(module: ModuleBase, container: _Container) -> ModuleInDB:
    module_repo = container.module_repo()
    # Note: Global module addition is system-level - no tenant-specific audit logging
    return await module_repo.add(module)


@router.post(
    "/{tenant_id}/",
    response_model=TenantInDB,
    description="Assign a list of modules to a tenant.",
    responses=responses.get_responses([404]),
)
async def add_module_to_tenant(
    tenant_id: UUID,
    module_ids: list[ModelId],
    container: _Container,
) -> TenantInDB:
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
        actor_id=None,  # System actor (no user)
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
