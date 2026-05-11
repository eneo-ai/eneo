"""
FastAPI router for tenant crawler settings management.

This module provides endpoints for system administrators to manage
tenant-specific crawler configuration that persists across restarts.

NOTE: Field constraints (ge, le) are derived from CRAWLER_SETTING_SPECS
in crawler_settings_helper.py which is the SINGLE SOURCE OF TRUTH.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from intric.authentication import auth
from intric.main.container.container import Container
from intric.main.exceptions import NotFoundException
from intric.server.dependencies.container import get_container
from intric.tenants.crawler_settings_models import (
    CrawlerSettingsResponse,
    CrawlerSettingsUpdate,
    DeleteSettingsResponse,
)

router = APIRouter(
    prefix="/tenants",
    dependencies=[
        Depends(auth.authenticate_super_api_key),
    ],
)


@router.put(
    "/{tenant_id}/crawler-settings",
    response_model=CrawlerSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Update tenant crawler settings",
    description="Update crawler settings for a specific tenant. "
    "Only provided fields are updated; missing fields retain previous values. "
    "Settings persist across server restarts and override environment defaults. "
    "System admin only.",
)
async def update_crawler_settings(
    tenant_id: UUID,
    request: CrawlerSettingsUpdate,
    container: Annotated[Container, Depends(get_container())],
) -> CrawlerSettingsResponse:
    """
    Update crawler settings for a tenant.

    Partial updates supported - only provided fields are changed.
    Settings are stored in the database and persist across restarts.

    Args:
        tenant_id: UUID of the tenant
        request: Settings to update (partial update supported)
        container: Dependency injection container

    Returns:
        CrawlerSettingsResponse with current effective settings

    Raises:
        HTTPException 404: Tenant not found
        HTTPException 422: Validation error
    """
    tenant_service = container.tenant_service()

    try:
        # Get only non-None values from request
        updates = request.model_dump(exclude_none=True)

        result = await tenant_service.update_crawler_settings(
            tenant_id=tenant_id,
            settings=updates,
        )

        return CrawlerSettingsResponse(
            tenant_id=result["tenant_id"],
            settings=result["settings"],
            overrides=result["overrides"],
            updated_at=result["updated_at"],
        )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )


@router.get(
    "/{tenant_id}/crawler-settings",
    response_model=CrawlerSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get tenant crawler settings",
    description="Get current crawler settings for a tenant. "
    "Returns effective settings (tenant overrides merged with environment defaults). "
    "System admin only.",
)
async def get_crawler_settings(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container())],
) -> CrawlerSettingsResponse:
    """
    Get current crawler settings for a tenant.

    Returns merged view: tenant overrides take precedence over env defaults.

    Args:
        tenant_id: UUID of the tenant
        container: Dependency injection container

    Returns:
        CrawlerSettingsResponse with current effective settings

    Raises:
        HTTPException 404: Tenant not found
    """
    tenant_service = container.tenant_service()

    try:
        result = await tenant_service.get_crawler_settings(tenant_id=tenant_id)

        return CrawlerSettingsResponse(
            tenant_id=result["tenant_id"],
            settings=result["settings"],
            overrides=result["overrides"],
            updated_at=result["updated_at"],
        )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.delete(
    "/{tenant_id}/crawler-settings",
    response_model=DeleteSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset tenant crawler settings",
    description="Delete all tenant-specific crawler settings, reverting to environment defaults. "
    "System admin only.",
)
async def delete_crawler_settings(
    tenant_id: UUID,
    container: Annotated[Container, Depends(get_container())],
) -> DeleteSettingsResponse:
    """
    Delete all tenant crawler settings, reverting to defaults.

    Args:
        tenant_id: UUID of the tenant
        container: Dependency injection container

    Returns:
        DeleteSettingsResponse with confirmation

    Raises:
        HTTPException 404: Tenant not found
    """
    tenant_service = container.tenant_service()

    try:
        result = await tenant_service.delete_crawler_settings(tenant_id=tenant_id)

        return DeleteSettingsResponse(
            tenant_id=result["tenant_id"],
            message="Crawler settings reset to defaults",
            deleted_keys=result["deleted_keys"],
        )
    except NotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
