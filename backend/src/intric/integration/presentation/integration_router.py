from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends

from intric.integration.presentation.models import (
    Integration,
    IntegrationList,
    IntegrationPreviewDataList,
    TenantIntegration,
    TenantIntegrationFilter,
    TenantIntegrationList,
    UserIntegrationList,
)
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

router = APIRouter()


@router.get(
    "/",
    response_model=IntegrationList,
    status_code=200,
)
async def get_integrations(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.integration_service()

    integrations = await service.get_integrations()

    assembler = container.integration_assembler()

    return assembler.to_paginated_response(integrations=integrations)


@router.get(
    "/tenant/",
    response_model=TenantIntegrationList,
    status_code=200,
)
async def get_tenant_integrations(
    filter: Optional[TenantIntegrationFilter] = None,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.tenant_integration_service()

    filter = TenantIntegrationFilter.DEFAULT if filter is None else filter

    tenant_integrations = await service.get_tenant_integrations(filter=filter)

    assembler = container.tenant_integration_assembler()
    return assembler.to_paginated_response(integrations=tenant_integrations)


@router.post(
    "/tenant/{integration_id}/",
    response_model=TenantIntegration,
    status_code=200,
)
async def add_tenant_integration(
    integration_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.tenant_integration_service()
    user = container.user()

    # Add tenant integration
    tenant_integration = await service.create_tenant_integration(integration_id=integration_id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.INTEGRATION_ADDED,
        entity_type=EntityType.INTEGRATION,
        entity_id=tenant_integration.id,
        description=f"Added {tenant_integration.integration.name} integration to tenant",
        metadata=AuditMetadata.standard(
            actor=user,
            target=tenant_integration,
            extra={"integration_type": tenant_integration.integration_type},
        ),
    )

    assembler = container.tenant_integration_assembler()
    return assembler.from_domain_to_model(item=tenant_integration)


@router.delete(
    "/tenant/{tenant_integration_id}/",
    status_code=204,
)
async def remove_tenant_integration(
    tenant_integration_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.tenant_integration_service()
    user = container.user()

    # Get tenant integration info BEFORE deletion (snapshot pattern)
    tenant_integration_repo = container.tenant_integration_repo()
    tenant_integration = await tenant_integration_repo.one(id=tenant_integration_id)

    # Delete tenant integration
    await service.remove_tenant_integration(tenant_integration_id=tenant_integration_id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.INTEGRATION_REMOVED,
        entity_type=EntityType.INTEGRATION,
        entity_id=tenant_integration_id,
        description=f"Removed {tenant_integration.integration.name} integration from tenant",
        metadata=AuditMetadata.standard(
            actor=user,
            target=tenant_integration,
            extra={"integration_type": tenant_integration.integration_type},
        ),
    )


@router.get(
    "/me/",
    response_model=UserIntegrationList,
    status_code=200,
)
async def get_user_integrations(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.user_integration_service()
    user = container.user()

    user_integrations = await service.get_my_integrations(user_id=user.id, tenant_id=user.tenant_id)

    assembler = container.user_integration_assembler()
    return assembler.to_paginated_response(integrations=user_integrations)


@router.delete(
    "/users/{user_integration_id}/",
    status_code=204,
)
async def disconnect_user_integration(
    user_integration_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.user_integration_service()
    user = container.user()

    # Get user integration info BEFORE deletion (snapshot pattern)
    user_integration_repo = container.user_integration_repo()
    user_integration = await user_integration_repo.one(id=user_integration_id)

    # Disconnect integration
    await service.disconnect_integration(user_integration_id=user_integration_id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.INTEGRATION_DISCONNECTED,
        entity_type=EntityType.INTEGRATION,
        entity_id=user_integration_id,
        description=f"Disconnected {user_integration.tenant_integration.integration.name} integration",
        metadata=AuditMetadata.standard(
            actor=user,
            target=user_integration,
            extra={
                "integration_name": user_integration.tenant_integration.integration.name,
                "integration_type": user_integration.integration_type,
            },
        ),
    )


@router.get(
    "/{user_integration_id}/preview/",
    response_model=IntegrationPreviewDataList,
    status_code=200,
)
async def get_integration_preview(
    user_integration_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.integration_preview_service()
    assembler = container.confluence_content_assembler()

    preview_data = await service.get_preview_data(user_integration_id=user_integration_id)

    return assembler.to_paginated_response(items=preview_data)


@router.get(
    "/{integration_id:uuid}/",
    response_model=Integration,
    status_code=200,
)
async def get_integration_by_id(
    integration_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.integration_service()

    integration = await service.get_integration_by_id(integration_id)

    assembler = container.integration_assembler()

    return assembler.from_domain_to_model(item=integration)
