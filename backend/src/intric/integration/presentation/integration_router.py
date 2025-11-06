from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.integration.presentation.models import (
    Integration,
    IntegrationList,
    IntegrationPreviewDataList,
    PaginatedSyncLogList,
    SharePointTreeResponse,
    SyncLog,
    TenantIntegration,
    TenantIntegrationFilter,
    TenantIntegrationList,
    UserIntegrationList,
)
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

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

    tenant_integration = await service.create_tenant_integration(integration_id=integration_id)
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

    await service.remove_tenant_integration(tenant_integration_id=tenant_integration_id)


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

    await service.disconnect_integration(user_integration_id=user_integration_id)


@router.get(
    "/sync-logs/{integration_knowledge_id:uuid}/",
    response_model=PaginatedSyncLogList,
    status_code=200,
)
async def get_sync_logs(
    integration_knowledge_id: UUID,
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of items per page"),
    container: Container = Depends(get_container(with_user=True)),
):
    """Get paginated sync history for an integration knowledge."""
    sync_log_repo = container.sync_log_repo()

    # Get total count
    total_count = await sync_log_repo.count_by_integration_knowledge(
        integration_knowledge_id=integration_knowledge_id
    )

    # Get paginated logs
    sync_logs = await sync_log_repo.get_by_integration_knowledge(
        integration_knowledge_id=integration_knowledge_id,
        limit=limit,
        offset=skip
    )

    # Convert domain entities to presentation models
    sync_log_models = [
        SyncLog(
            id=log.id,
            integration_knowledge_id=log.integration_knowledge_id,
            sync_type=log.sync_type,
            status=log.status,
            metadata=log.metadata,
            error_message=log.error_message,
            started_at=log.started_at,
            completed_at=log.completed_at,
            created_at=log.created_at,
        )
        for log in sync_logs
    ]

    return PaginatedSyncLogList(
        items=sync_log_models,
        total_count=total_count,
        page_size=limit,
        offset=skip
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
    "/{user_integration_id:uuid}/sharepoint/tree/",
    response_model=SharePointTreeResponse,
    status_code=200,
)
async def get_sharepoint_folder_tree(
    user_integration_id: UUID,
    site_id: str = Query(..., description="SharePoint site ID"),
    folder_id: Optional[str] = Query(None, description="Folder ID (null for root)"),
    folder_path: str = Query("", description="Current folder path"),
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.sharepoint_tree_service()

    # Convert string "null" to actual None
    if folder_id == "null":
        folder_id = None

    tree_data = await service.get_folder_tree(
        user_integration_id=user_integration_id,
        site_id=site_id,
        folder_id=folder_id,
        folder_path=folder_path,
    )

    return SharePointTreeResponse(**tree_data)


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
