from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.integration.presentation.models import (
    Integration,
    IntegrationList,
    IntegrationPreviewDataList,
    PaginatedSyncLogList,
    SharePointSearchResponse,
    SharePointTreeResponse,
    SyncLog,
    TenantIntegration,
    TenantIntegrationFilter,
    TenantIntegrationList,
    UserIntegrationList,
)
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


@router.get(
    "/",
    response_model=IntegrationList,
    status_code=200,
    description="List all available integrations.",
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_integrations(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.integration_service()

    integrations = await service.get_integrations()

    assembler = container.integration_assembler()

    return assembler.to_paginated_response(integrations=integrations)


@router.get(
    "/tenant/",
    response_model=TenantIntegrationList,
    status_code=200,
    description="List the tenant's integrations, optionally filtered.",
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_tenant_integrations(
    container: Annotated[Container, Depends(get_container(with_user=True))],
    filter: Optional[TenantIntegrationFilter] = None,
):
    service = container.tenant_integration_service()

    filter = TenantIntegrationFilter.DEFAULT if filter is None else filter

    tenant_integrations = await service.get_tenant_integrations(filter=filter)

    assembler = container.tenant_integration_assembler()
    return assembler.to_paginated_response(integrations=tenant_integrations)


@router.post(
    "/tenant/add/{integration_id}/",
    response_model=TenantIntegration,
    status_code=200,
    description="Add an integration to the tenant. Requires administrator permission.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def add_tenant_integration(
    integration_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.tenant_integration_service()
    user = container.user()

    # Add tenant integration
    tenant_integration = await service.create_tenant_integration(
        integration_id=integration_id
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
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
    "/tenant/remove/{tenant_integration_id}/",
    status_code=204,
    description="Remove an integration from the tenant. Requires administrator permission.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def remove_tenant_integration(
    tenant_integration_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.tenant_integration_service()
    user = container.user()

    tenant_integration = await service.remove_tenant_integration(
        tenant_integration_id=tenant_integration_id
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
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
    description="List the current user's personal integrations.",
    responses=responses.get_responses([]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_user_integrations(
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Get user's personal integrations.

    Only returns user_oauth integrations (personal account connections).
    Tenant app integrations are managed in admin panel and not shown here.
    """
    service = container.user_integration_service()
    user = container.user()

    user_integrations = await service.get_my_integrations(
        user_id=user.id, tenant_id=user.tenant_id
    )

    # Filter out tenant_app integrations - they should only appear in admin panel
    personal_integrations = [
        integration
        for integration in user_integrations
        if integration.auth_type != "tenant_app"
    ]

    # Check if tenant SharePoint app is configured and active
    tenant_sharepoint_app_repo = container.tenant_sharepoint_app_repo()
    tenant_app = await tenant_sharepoint_app_repo.one_or_none(tenant_id=user.tenant_id)
    tenant_app_configured = tenant_app is not None and tenant_app.is_active

    assembler = container.user_integration_assembler()
    return assembler.to_paginated_response(
        integrations=personal_integrations, tenant_app_configured=tenant_app_configured
    )


@router.get(
    "/spaces/{space_id}/available/",
    response_model=UserIntegrationList,
    status_code=200,
    description="List integrations available for a specific space.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="SpaceService checks current space read access before listing available integrations.",
)
async def get_available_integrations_for_space(
    space_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Get integrations available for a specific space, filtered by space type and auth type.

    - Personal spaces: Only user OAuth integrations
    - Shared/Organization spaces: Both tenant app and user OAuth integrations
    """
    space = await container.space_service().get_space(space_id)
    user = container.user()

    service = container.user_integration_service()
    user_integrations = await service.get_available_integrations_for_space(space=space)

    # Check if tenant SharePoint app is configured and active
    tenant_sharepoint_app_repo = container.tenant_sharepoint_app_repo()
    tenant_app = await tenant_sharepoint_app_repo.one_or_none(tenant_id=user.tenant_id)
    tenant_app_configured = tenant_app is not None and tenant_app.is_active

    assembler = container.user_integration_assembler()
    return assembler.to_paginated_response(
        integrations=user_integrations, tenant_app_configured=tenant_app_configured
    )


@router.delete(
    "/users/{user_integration_id}/",
    status_code=204,
    description="Disconnect the current user's integration.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def disconnect_user_integration(
    user_integration_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.user_integration_service()
    user = container.user()

    user_integration = await service.disconnect_integration(
        user_integration_id=user_integration_id
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
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
    "/sync-logs/{integration_knowledge_id:uuid}/",
    response_model=PaginatedSyncLogList,
    status_code=200,
    description="Get paginated sync history for an integration knowledge.",
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_sync_logs(
    integration_knowledge_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    skip: Annotated[int, Query(ge=0, description="Number of items to skip")] = 0,
    limit: Annotated[
        int, Query(ge=1, le=100, description="Number of items per page")
    ] = 10,
):
    """Get paginated sync history for an integration knowledge."""
    service = container.integration_knowledge_service()
    await service.require_sync_log_access(integration_knowledge_id)
    sync_log_repo = container.sync_log_repo()
    tenant_id = container.user().tenant_id

    # Get total count
    total_count = await sync_log_repo.count_by_integration_knowledge(
        integration_knowledge_id=integration_knowledge_id, tenant_id=tenant_id
    )

    # Get paginated logs
    sync_logs = await sync_log_repo.get_by_integration_knowledge(
        integration_knowledge_id=integration_knowledge_id,
        tenant_id=tenant_id,
        limit=limit,
        offset=skip,
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
            created_at=log.created_at or log.started_at,
        )
        for log in sync_logs
    ]

    return PaginatedSyncLogList(
        items=sync_log_models, total_count=total_count, page_size=limit, offset=skip
    )


@router.get(
    "/{user_integration_id}/preview/",
    response_model=IntegrationPreviewDataList,
    status_code=200,
    description="Get preview data for a user integration.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_integration_preview(
    user_integration_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.integration_preview_service()
    assembler = container.confluence_content_assembler()

    preview_data = await service.get_preview_data(
        user_integration_id=user_integration_id
    )

    return assembler.to_paginated_response(items=preview_data)


@router.get(
    "/{user_integration_id:uuid}/sharepoint/search/",
    response_model=SharePointSearchResponse,
    status_code=200,
    description=(
        "Search a SharePoint library or OneDrive by free text and column values, "
        "across every folder."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def search_sharepoint_library(
    user_integration_id: UUID,
    space_id: Annotated[
        UUID, Query(description="Space ID (requires integration import rights)")
    ],
    container: Annotated[Container, Depends(get_container(with_user=True))],
    site_id: Annotated[
        Optional[str], Query(description="SharePoint site ID (required for SharePoint)")
    ] = None,
    drive_id: Annotated[
        Optional[str], Query(description="Drive ID (required for OneDrive)")
    ] = None,
    q: Annotated[
        str,
        Query(description="Free text matched against names, content and properties"),
    ] = "",
    filter: Annotated[
        list[str],
        Query(
            description=(
                "Column filter as `Column:value`, repeatable. Columns come from the "
                "tree response; yes/no columns take true or false."
            )
        ),
    ] = [],
):
    """Find files anywhere in a library, so a person need not browse folder by folder."""
    from eneo.integration.infrastructure.preview_service.sharepoint_search import (
        parse_filter_params,
    )
    from eneo.main.exceptions import BadRequestException

    service = container.sharepoint_tree_service()
    if not site_id and not drive_id:
        raise BadRequestException("Either site_id or drive_id must be provided")
    result = await service.search_library(
        user_integration_id=user_integration_id,
        space_id=space_id,
        site_id=site_id,
        drive_id=drive_id,
        text=q,
        filters=parse_filter_params(filter),
    )
    return SharePointSearchResponse(**result)


@router.get(
    "/{user_integration_id:uuid}/sharepoint/tree/",
    response_model=SharePointTreeResponse,
    status_code=200,
    description="Get SharePoint/OneDrive folder tree for a user integration.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_sharepoint_folder_tree(
    user_integration_id: UUID,
    space_id: Annotated[
        UUID, Query(description="Space ID (requires integration import rights)")
    ],
    container: Annotated[Container, Depends(get_container(with_user=True))],
    site_id: Annotated[
        Optional[str],
        Query(description="SharePoint site ID (required for SharePoint)"),
    ] = None,
    drive_id: Annotated[
        Optional[str], Query(description="Drive ID (required for OneDrive)")
    ] = None,
    folder_id: Annotated[
        Optional[str], Query(description="Folder ID (null for root)")
    ] = None,
    folder_path: Annotated[str, Query(description="Current folder path")] = "",
):
    """Browse an authorized SharePoint/OneDrive connection in an importable space.

    Uses the selected connection's identity after ownership, tenant and space
    authorization. Organization connections additionally require admin permission.

    Provide site_id for SharePoint sites, or drive_id for OneDrive.
    """
    from eneo.main.exceptions import (
        BadRequestException,
        NotFoundException,
        UnauthorizedException,
    )
    from eneo.main.logging import get_logger

    logger = get_logger(__name__)
    service = container.sharepoint_tree_service()

    # Validate that at least one of site_id or drive_id is provided
    if not site_id and not drive_id:
        raise BadRequestException("Either site_id or drive_id must be provided")

    # Convert string "null" or empty string to actual None
    if folder_id == "null" or folder_id == "":
        folder_id = None

    try:
        tree_data = await service.get_folder_tree(
            user_integration_id=user_integration_id,
            space_id=space_id,
            site_id=site_id,
            drive_id=drive_id,
            folder_id=folder_id,
            folder_path=folder_path,
        )
        return SharePointTreeResponse(**tree_data)
    except (NotFoundException, BadRequestException, UnauthorizedException):
        # The service raises typed domain exceptions with the correct HTTP status;
        # let them propagate to the global handlers instead of remapping by string.
        raise
    except Exception as e:
        # Unexpected errors
        logger.error(
            f"Unexpected error in SharePoint tree endpoint: {type(e).__name__}: {str(e)}",
            extra={
                "user_integration_id": str(user_integration_id),
                "space_id": str(space_id),
                "site_id": site_id,
            },
            exc_info=True,
        )
        raise BadRequestException(f"Failed to fetch SharePoint folder tree: {str(e)}")


@router.get(
    "/{integration_id:uuid}/",
    response_model=Integration,
    status_code=200,
    description="Get a single integration by ID.",
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason="Integration services enforce tenant, user and space access for this operation.",
)
async def get_integration_by_id(
    integration_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    service = container.integration_service()

    integration = await service.get_integration_by_id(integration_id)

    assembler = container.integration_assembler()

    return assembler.from_domain_to_model(item=integration)
