"""
FastAPI router for tenant crawler settings management.

This module provides endpoints for system administrators to manage
tenant-specific crawler configuration that persists across restarts.

NOTE: Field constraints (ge, le) are derived from CRAWLER_SETTING_SPECS
in crawler_settings_helper.py which is the SINGLE SOURCE OF TRUTH.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from intric.authentication import auth
from intric.main.container.container import Container
from intric.main.exceptions import NotFoundException
from intric.server.dependencies.container import get_container
from intric.tenants.crawler_settings_helper import CRAWLER_SETTING_SPECS

# Extract specs for cleaner Field definitions
_SPECS = CRAWLER_SETTING_SPECS

router = APIRouter(
    prefix="/tenants",
    dependencies=[
        Depends(auth.authenticate_super_api_key),
    ],
)


class CrawlerSettingsUpdate(BaseModel):
    """
    Request model for updating tenant crawler settings.

    All fields are optional - only provided fields will be updated.
    Missing fields retain their previous values or fall back to environment defaults.

    Field constraints are derived from CRAWLER_SETTING_SPECS (single source of truth).

    Example - Full configuration:
        {
            "crawl_max_length": 14400,
            "download_timeout": 90,
            "download_max_size": 10485760,
            "dns_timeout": 30,
            "retry_times": 2,
            "closespider_itemcount": 20000,
            "obey_robots": true,
            "autothrottle_enabled": true,
            "tenant_worker_concurrency_limit": 4,
            "crawl_stale_threshold_minutes": 30,
            "crawl_heartbeat_interval_seconds": 300,
            "crawl_feeder_enabled": false,
            "crawl_feeder_interval_seconds": 10,
            "crawl_feeder_batch_size": 10,
            "crawl_job_max_age_seconds": 1800
        }

    Example - Partial update (adjust timeouts only):
        {
            "download_timeout": 120,
            "dns_timeout": 45
        }
    """

    # Timeout settings (seconds)
    crawl_max_length: int | None = Field(
        None,
        ge=_SPECS["crawl_max_length"]["min"],
        le=_SPECS["crawl_max_length"]["max"],
        description=_SPECS["crawl_max_length"]["description"],
        examples=[14400],
    )
    download_timeout: int | None = Field(
        None,
        ge=_SPECS["download_timeout"]["min"],
        le=_SPECS["download_timeout"]["max"],
        description=_SPECS["download_timeout"]["description"],
        examples=[90],
    )
    download_max_size: int | None = Field(
        None,
        ge=_SPECS["download_max_size"]["min"],
        le=_SPECS["download_max_size"]["max"],
        description=_SPECS["download_max_size"]["description"],
        examples=[10485760],
    )
    dns_timeout: int | None = Field(
        None,
        ge=_SPECS["dns_timeout"]["min"],
        le=_SPECS["dns_timeout"]["max"],
        description=_SPECS["dns_timeout"]["description"],
        examples=[30],
    )

    # Retry settings
    retry_times: int | None = Field(
        None,
        ge=_SPECS["retry_times"]["min"],
        le=_SPECS["retry_times"]["max"],
        description=_SPECS["retry_times"]["description"],
        examples=[2],
    )

    # Item limits
    closespider_itemcount: int | None = Field(
        None,
        ge=_SPECS["closespider_itemcount"]["min"],
        le=_SPECS["closespider_itemcount"]["max"],
        description=_SPECS["closespider_itemcount"]["description"],
        examples=[20000],
    )

    # Boolean settings
    obey_robots: bool | None = Field(
        None,
        description=_SPECS["obey_robots"]["description"],
        examples=[True],
    )
    autothrottle_enabled: bool | None = Field(
        None,
        description=_SPECS["autothrottle_enabled"]["description"],
        examples=[True],
    )

    # Concurrency settings
    tenant_worker_concurrency_limit: int | None = Field(
        None,
        ge=_SPECS["tenant_worker_concurrency_limit"]["min"],
        le=_SPECS["tenant_worker_concurrency_limit"]["max"],
        description=_SPECS["tenant_worker_concurrency_limit"]["description"],
        examples=[4],
    )

    # Reliability settings
    crawl_stale_threshold_minutes: int | None = Field(
        None,
        ge=_SPECS["crawl_stale_threshold_minutes"]["min"],
        le=_SPECS["crawl_stale_threshold_minutes"]["max"],
        description=_SPECS["crawl_stale_threshold_minutes"]["description"],
        examples=[30],
    )
    crawl_heartbeat_interval_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_heartbeat_interval_seconds"]["min"],
        le=_SPECS["crawl_heartbeat_interval_seconds"]["max"],
        description=_SPECS["crawl_heartbeat_interval_seconds"]["description"],
        examples=[300],
    )

    # Feeder settings
    crawl_feeder_enabled: bool | None = Field(
        None,
        description=_SPECS["crawl_feeder_enabled"]["description"],
        examples=[False],
    )
    crawl_feeder_interval_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_feeder_interval_seconds"]["min"],
        le=_SPECS["crawl_feeder_interval_seconds"]["max"],
        description=_SPECS["crawl_feeder_interval_seconds"]["description"],
        examples=[10],
    )
    crawl_feeder_batch_size: int | None = Field(
        None,
        ge=_SPECS["crawl_feeder_batch_size"]["min"],
        le=_SPECS["crawl_feeder_batch_size"]["max"],
        description=_SPECS["crawl_feeder_batch_size"]["description"],
        examples=[10],
    )

    # Job age limit
    crawl_job_max_age_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_job_max_age_seconds"]["min"],
        le=_SPECS["crawl_job_max_age_seconds"]["max"],
        description=_SPECS["crawl_job_max_age_seconds"]["description"],
        examples=[1800],
    )


class CrawlerSettingsResponse(BaseModel):
    """
    Response model for crawler settings operations.

    Returns current settings merged with environment defaults.
    Tenant overrides are highlighted.

    Example:
        {
            "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
            "settings": {
                "crawl_max_length": 14400,
                "download_timeout": 90,
                "download_max_size": 10485760,
                "dns_timeout": 30,
                "retry_times": 2,
                "closespider_itemcount": 20000,
                "obey_robots": true,
                "autothrottle_enabled": true,
                "tenant_worker_concurrency_limit": 4,
                "crawl_stale_threshold_minutes": 30,
                "crawl_heartbeat_interval_seconds": 300,
                "crawl_feeder_enabled": false,
                "crawl_feeder_interval_seconds": 10,
                "crawl_feeder_batch_size": 10,
                "crawl_job_max_age_seconds": 1800
            },
            "overrides": ["download_timeout", "dns_timeout"],
            "updated_at": "2025-10-22T10:00:00+00:00"
        }
    """

    tenant_id: UUID = Field(..., description="Tenant UUID")
    settings: dict[str, Any] = Field(
        ...,
        description="Current effective settings (tenant overrides + env defaults)",
        examples=[
            {
                "crawl_max_length": 14400,
                "download_timeout": 90,
                "download_max_size": 10485760,
                "dns_timeout": 30,
                "retry_times": 2,
                "closespider_itemcount": 20000,
                "obey_robots": True,
                "autothrottle_enabled": True,
                "tenant_worker_concurrency_limit": 4,
                "crawl_stale_threshold_minutes": 30,
                "crawl_heartbeat_interval_seconds": 300,
                "crawl_feeder_enabled": False,
                "crawl_feeder_interval_seconds": 10,
                "crawl_feeder_batch_size": 10,
                "crawl_job_max_age_seconds": 1800,
            }
        ],
    )
    overrides: list[str] = Field(
        ...,
        description="List of setting keys that have tenant-specific overrides",
        examples=[["download_timeout", "dns_timeout"]],
    )
    updated_at: datetime | None = Field(
        None, description="Timestamp of last settings update"
    )


class DeleteSettingsResponse(BaseModel):
    """
    Response model for deleting tenant crawler settings.

    Example:
        {
            "tenant_id": "123e4567-e89b-12d3-a456-426614174000",
            "message": "Crawler settings reset to defaults",
            "deleted_keys": ["download_timeout", "dns_timeout"]
        }
    """

    tenant_id: UUID = Field(..., description="Tenant UUID")
    message: str = Field(..., description="Confirmation message")
    deleted_keys: list[str] = Field(
        ..., description="List of setting keys that were removed"
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
    container: Container = Depends(get_container()),
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
    container: Container = Depends(get_container()),
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
    container: Container = Depends(get_container()),
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
