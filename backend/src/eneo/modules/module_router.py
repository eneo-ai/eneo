from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

# Audit logging - module level imports for consistency
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication import auth
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import ModelId, PaginatedResponse
from eneo.modules.module import (
    ModuleClientConfig,
    ModuleCreate,
    ModuleInDB,
    ModuleTenantAssignment,
    ModuleTenantClientConfig,
)
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.tenants.tenant import TenantInDB

router = APIRouter(
    dependencies=[Depends(auth.authenticate_super_duper_api_key)],
    responses=responses.get_responses([401]),
)

_Container = Annotated[Container, Depends(get_container())]
_MutationContainer = Annotated[
    Container, Depends(get_container(transaction_scope="function"))
]


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
    description=(
        "Register a new global module. The module key is immutable, "
        "case-sensitive and restricted to a URL-safe slug: letters and "
        "digits plus '.', '_' or '-', starting with a letter or digit."
    ),
    responses=responses.get_responses([409]),
)
async def add_module(module: ModuleCreate, container: _MutationContainer) -> ModuleInDB:
    module_repo = container.module_repo()
    # Note: Global module addition is system-level - no tenant-specific audit logging
    return await module_repo.add(module)


@router.patch(
    "/{tenant_id}/{module_id}/client-config/",
    response_model=ModuleTenantClientConfig,
    description=(
        "Set a tenant module's auth-broker client config: the exact-match "
        "redirect URI allowlist and the sk_ service key allowed to exchange "
        "that tenant's login tickets."
    ),
    responses=responses.get_responses([400, 404]),
)
async def update_module_client_config(
    tenant_id: UUID,
    module_id: UUID,
    config: ModuleClientConfig,
    container: _MutationContainer,
) -> ModuleTenantClientConfig:
    updates = config.update_values()
    if not updates:
        raise BadRequestException(
            "Module client config PATCH requires at least one field."
        )

    module_repo = container.module_repo()
    module = await module_repo.get_module(module_id)
    if module is None:
        raise NotFoundException("Module not found.")

    previous = await module_repo.get_module_client_config(
        tenant_id=tenant_id, module_id=module_id
    )
    if previous is None:
        raise NotFoundException("Module is not enabled for this tenant.")

    if "service_key_id" in updates and config.service_key_id is not None:
        await container.module_auth_broker().validate_client_config_service_key(
            tenant_id=tenant_id,
            service_key_id=config.service_key_id,
        )

    updated = await module_repo.update_client_config(
        tenant_id=tenant_id, module_id=module_id, config=config
    )
    if updated is None:
        raise NotFoundException("Module is not enabled for this tenant.")

    audit_service = container.audit_service()
    # Persist the audit row in the mutation's function-scoped transaction so
    # a failed commit cannot leave a success event behind in the async queue.
    await audit_service.log(
        tenant_id=tenant_id,
        actor_id=None,
        actor_type=ActorType.SYSTEM,
        action=ActionType.MODULE_CLIENT_CONFIG_UPDATED,
        entity_type=EntityType.MODULE,
        entity_id=module_id,
        description=f"Sysadmin updated module auth client config for '{module.name}'",
        metadata={
            "actor": {"type": "sysadmin", "via": "super_duper_api_key"},
            "target": {
                "tenant_id": str(tenant_id),
                "module_id": str(module_id),
                "module_name": module.name,
            },
            "before": previous.model_dump(mode="json"),
            "after": updated.model_dump(mode="json"),
        },
    )

    return updated


@router.post(
    "/{tenant_id}/",
    response_model=TenantInDB,
    description=(
        "Replace the tenant's complete module set. Prefer the targeted PUT and "
        "DELETE routes when enabling or disabling one module."
    ),
    responses=responses.get_responses([404]),
)
async def add_module_to_tenant(
    tenant_id: UUID,
    module_ids: list[ModelId],
    container: _MutationContainer,
) -> TenantInDB:
    """Replace the tenant's complete module set with the supplied IDs."""
    tenant_service = container.tenant_service()

    updated_tenant = await tenant_service.replace_modules(
        tenant_id=tenant_id, list_of_module_ids=module_ids
    )
    effective_module_ids = [module.id for module in updated_tenant.modules]

    # Audit logging (sysadmin operation - system actor)
    audit_service = container.audit_service()
    await audit_service.log(
        tenant_id=tenant_id,
        actor_id=None,  # System actor (no user)
        actor_type=ActorType.SYSTEM,
        action=ActionType.MODULE_SET_REPLACED,
        entity_type=EntityType.MODULE,
        entity_id=tenant_id,  # Use tenant as entity ID
        description=(
            "Sysadmin replaced tenant module set with "
            f"{len(effective_module_ids)} module(s)"
        ),
        metadata={
            "actor": {"type": "sysadmin", "via": "super_duper_api_key"},
            "target": {
                "tenant_id": str(tenant_id),
                "tenant_name": updated_tenant.name,
                "replacement_module_count": len(effective_module_ids),
                "module_ids": [str(module_id) for module_id in effective_module_ids],
            },
        },
    )

    return updated_tenant


@router.put(
    "/{tenant_id}/{module_id}/",
    response_model=ModuleTenantAssignment,
    description="Enable one module without changing the tenant's other modules.",
    responses=responses.get_responses([404]),
)
async def enable_module_for_tenant(
    tenant_id: UUID,
    module_id: UUID,
    container: _MutationContainer,
) -> ModuleTenantAssignment:
    assignment = await container.tenant_service().enable_module(
        tenant_id=tenant_id, module_id=module_id
    )
    if assignment.changed:
        await container.audit_service().log(
            tenant_id=tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=ActionType.MODULE_ADDED_TO_TENANT,
            entity_type=EntityType.MODULE,
            entity_id=module_id,
            description=f"Sysadmin enabled module '{assignment.module_key}' for tenant",
            metadata={
                "actor": {"type": "sysadmin", "via": "super_duper_api_key"},
                "target": {
                    "tenant_id": str(tenant_id),
                    "module_id": str(module_id),
                    "module_name": assignment.module_key,
                },
            },
        )
    return assignment


@router.delete(
    "/{tenant_id}/{module_id}/",
    response_model=ModuleTenantAssignment,
    description=(
        "Disable one module and delete its tenant-specific callback and service-key "
        "binding."
    ),
    responses=responses.get_responses([404]),
)
async def disable_module_for_tenant(
    tenant_id: UUID,
    module_id: UUID,
    container: _MutationContainer,
) -> ModuleTenantAssignment:
    assignment = await container.tenant_service().disable_module(
        tenant_id=tenant_id, module_id=module_id
    )
    if assignment.changed:
        await container.audit_service().log(
            tenant_id=tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=ActionType.MODULE_REMOVED_FROM_TENANT,
            entity_type=EntityType.MODULE,
            entity_id=module_id,
            description=f"Sysadmin disabled module '{assignment.module_key}' for tenant",
            metadata={
                "actor": {"type": "sysadmin", "via": "super_duper_api_key"},
                "target": {
                    "tenant_id": str(tenant_id),
                    "module_id": str(module_id),
                    "module_name": assignment.module_key,
                },
            },
        )
    return assignment
