from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Security
from pydantic import BaseModel, Field

from intric.ai_models.completion_models.completion_model import (
    CompletionModelCreate,
    CompletionModelSparse,
    CompletionModelUpdate,
)
from intric.ai_models.completion_models.completion_models_repo import (
    CompletionModelsRepository,
)
from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelCreate,
    EmbeddingModelSparse,
    EmbeddingModelUpdate as EmbeddingModelMetadataUpdate,
)
from intric.ai_models.embedding_models.embedding_models_repo import (
    AdminEmbeddingModelsService,
)
from intric.allowed_origins.allowed_origin_models import (
    AllowedOriginCreate,
    AllowedOriginInDB,
)
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import DeleteResponse, PaginatedResponse
from intric.observability.debug_toggle import DebugFlag, get_debug_flag, set_debug_flag
from intric.server import protocol
from intric.server.dependencies.container import get_container, get_container_for_sysadmin
from intric.server.protocol import responses
from intric.tenants.tenant import TenantBase, TenantUpdatePublic, TenantWithMaskedCredentials
from intric.users.user import UserAddSuperAdmin, UserCreated, UserInDB, UserUpdatePublic
from intric.authentication import auth
from intric.worker.usage_stats_tasks import recalculate_tenant_usage_stats_direct
from intric.completion_models.presentation.completion_model_models import (
    ModelMigrationRequest,
    MigrationResult,
)

logger = get_logger(__name__)

router = APIRouter(dependencies=[Security(auth.authenticate_super_api_key)])


class OIDCDebugToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Enable or disable OIDC debug logging")
    duration_minutes: int | None = Field(
        30,
        ge=1,
        le=120,
        description="Duration in minutes before the toggle auto-expires (max 120)",
    )
    reason: str | None = Field(
        None,
        max_length=200,
        description="Optional note for audit trail",
    )


class OIDCDebugToggleResponse(BaseModel):
    enabled: bool
    enabled_at: datetime | None
    enabled_by: str | None
    expires_at: datetime | None
    reason: str | None
    backend: str

    @classmethod
    def from_flag(cls, flag: DebugFlag, *, backend: str) -> "OIDCDebugToggleResponse":
        return cls(
            enabled=flag.enabled,
            enabled_at=flag.enabled_at,
            enabled_by=flag.enabled_by,
            expires_at=flag.expires_at,
            reason=flag.reason,
            backend=backend,
        )


@router.post(
    "/users/",
    response_model=UserCreated,
    responses=responses.get_responses([400, 401]),
)
async def register_new_user(
    new_user: UserAddSuperAdmin, container: Container = Depends(get_container())
):
    user_service = container.user_service()
    created_user, access_token, api_key = await user_service.register(new_user)

    return UserCreated(
        **created_user.model_dump(exclude={"api_key"}),
        access_token=access_token,
        api_key=api_key,
    )


@router.get("/users/", response_model=PaginatedResponse[UserInDB])
async def get_all_users(
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    users_in_db = await user_service.get_all_users()

    return protocol.to_paginated_response(users_in_db)


@router.get("/users/{user_id}/", response_model=UserInDB)
async def get_user(
    user_id: UUID,
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    return await user_service.get_user(user_id)


@router.delete("/users/{user_id}/", response_model=DeleteResponse)
async def delete_user(
    user_id: UUID,
    container: Container = Depends(get_container()),
):
    user_service = container.user_service()
    success = await user_service.delete_user(user_id)

    return DeleteResponse(success=success)


@router.post("/users/{user_id}/", response_model=UserInDB)
async def update_user(
    user_id: UUID,
    user_update: UserUpdatePublic,
    container: Container = Depends(get_container()),
):
    """Omitted fields are not updated."""
    user_service = container.user_service()
    return await user_service.update_user(user_id, user_update)


@router.post("/users/{user_id}/access-token/", include_in_schema=False)
async def get_access_token(user_id: UUID, container: Container = Depends(get_container())):
    user_repo = container.user_repo()
    auth_service = container.auth_service()

    user = await user_repo.get_user_by_id(user_id)

    return auth_service.create_access_token_for_user(user)


@router.get("/tenants/", response_model=PaginatedResponse[TenantWithMaskedCredentials])
async def get_tenants(domain: str | None = None, container: Container = Depends(get_container())):
    """Get all tenants with masked API credentials.

    Returns tenant information with API keys masked to show only last 4 characters.
    This prevents exposing full API keys through the API endpoint.

    Args:
        domain: Optional domain filter
        container: Dependency injection container

    Returns:
        Paginated list of tenants with masked credentials
    """
    tenant_service = container.tenant_service()

    tenants = await tenant_service.get_all_tenants(domain)

    # Mask API credentials before returning
    masked_tenants = [TenantWithMaskedCredentials.from_tenant(t) for t in tenants]

    return protocol.to_paginated_response(masked_tenants)


@router.post(
    "/tenants/",
    response_model=TenantWithMaskedCredentials,
    responses=responses.get_responses([400]),
)
async def create_tenant(tenant: TenantBase, container: Container = Depends(get_container())):
    tenant_service = container.tenant_service()

    created_tenant = await tenant_service.create_tenant(tenant)
    return TenantWithMaskedCredentials.from_tenant(created_tenant)


@router.post(
    "/tenants/{id}/",
    response_model=TenantWithMaskedCredentials,
    responses=responses.get_responses([404]),
)
async def update_tenant(
    id: UUID,
    tenant: TenantUpdatePublic,
    container: Container = Depends(get_container()),
):
    tenant_service = container.tenant_service()

    updated_tenant = await tenant_service.update_tenant(tenant, id)
    return TenantWithMaskedCredentials.from_tenant(updated_tenant)


@router.delete(
    "/tenants/{id}/",
    response_model=TenantWithMaskedCredentials,
    responses=responses.get_responses([404]),
)
async def delete_tenant_by_id(id: UUID, container: Container = Depends(get_container())):
    tenant_service = container.tenant_service()

    deleted_tenant = await tenant_service.delete_tenant(id)
    return TenantWithMaskedCredentials.from_tenant(deleted_tenant)


@router.get("/predefined-roles/")
async def get_predefined_roles(
    container: Container = Depends(get_container()),
):
    return await container.predefined_role_service().get_predefined_roles()


@router.post("/crawl-all-weekly-websites/")
async def crawl_all_weekly_websites(
    container: Container = Depends(get_container()),
):
    sysadmin_service = container.sysadmin_service()

    return await sysadmin_service.run_crawl_on_weekly_websites()


def _mask_actor_label() -> str:
    return "super_api_key"


def _get_storage_backend(redis_client) -> str:
    return "redis" if redis_client is not None else "file"


@router.post(
    "/observability/oidc-debug/",
    response_model=OIDCDebugToggleResponse,
    summary="Enable or disable OIDC debug logging",
    description=(
        "Turns verbose OIDC diagnostics on or off for a limited window. "
        "Requires super API key."
    ),
    responses={
        200: {"description": "Debug flag state updated."},
        401: {"description": "Missing or invalid super API key."},
    },
)
async def toggle_oidc_debug(
    payload: OIDCDebugToggleRequest,
    container: Container = Depends(get_container_for_sysadmin()),
):
    try:
        redis_client = container.redis_client()
    except Exception:  # pragma: no cover - defensive fallback
        redis_client = None

    duration = timedelta(minutes=payload.duration_minutes or 30)
    flag = await set_debug_flag(
        redis_client,
        enabled=payload.enabled,
        enabled_by=_mask_actor_label(),
        duration=duration,
        reason=payload.reason,
    )

    logger.warning(
        "OIDC debug flag updated",
        extra={
            "enabled": flag.enabled,
            "expires_at": flag.expires_at.isoformat() if flag.expires_at else None,
            "backend": _get_storage_backend(redis_client),
            "reason": flag.reason,
        },
    )

    return OIDCDebugToggleResponse.from_flag(
        flag,
        backend=_get_storage_backend(redis_client),
    )


@router.get(
    "/observability/oidc-debug/",
    response_model=OIDCDebugToggleResponse,
    summary="Get current OIDC debug toggle status",
    description="Returns whether OIDC debug logging is currently enabled and when it expires.",
    responses={
        200: {"description": "Current state of the OIDC debug toggle."},
        401: {"description": "Missing or invalid super API key."},
    },
)
async def get_oidc_debug_status(
    container: Container = Depends(get_container_for_sysadmin()),
):
    try:
        redis_client = container.redis_client()
    except Exception:  # pragma: no cover - defensive fallback
        redis_client = None

    flag = await get_debug_flag(redis_client)
    return OIDCDebugToggleResponse.from_flag(
        flag,
        backend=_get_storage_backend(redis_client),
    )


# CRUD Operations for Completion Models

@router.post(
    "/completion-models/create",
    response_model=CompletionModelSparse,
    responses=responses.get_responses([400, 401]),
)
async def create_completion_model(
    model_data: CompletionModelCreate,
    container: Container = Depends(get_container_for_sysadmin()),
) -> CompletionModelSparse:
    """
    Create a new completion model (system-wide operation).

    Requires: X-API-Key header with INTRIC_SUPER_API_KEY
    """
    session = container.session()
    async with session.begin():
        repo = CompletionModelsRepository(session=session)
        model = await repo.create_model(model_data)

    return model


@router.put(
    "/completion-models/{id}/metadata",
    response_model=CompletionModelSparse,
    responses=responses.get_responses([404, 401]),
)
async def update_completion_model_metadata(
    id: UUID,
    model_data: CompletionModelUpdate,
    container: Container = Depends(get_container_for_sysadmin()),
) -> CompletionModelSparse:
    """
    Update completion model metadata (system-wide operation).

    Requires: X-API-Key header with INTRIC_SUPER_API_KEY
    """
    session = container.session()
    async with session.begin():
        repo = CompletionModelsRepository(session=session)

        # Ensure model_data has the id
        update_with_id = CompletionModelUpdate(id=id, **model_data.model_dump(exclude={'id'}, exclude_unset=True))
        model = await repo.update_model(update_with_id)

    return model


@router.delete(
    "/completion-models/{id}",
    responses=responses.get_responses([404, 400, 401]),
)
async def delete_completion_model(
    id: UUID,
    force: bool = Query(False, description="Force delete even if in use"),
    container: Container = Depends(get_container_for_sysadmin()),
):
    """
    Delete a completion model (system-wide operation).

    Requires: X-API-Key header with INTRIC_SUPER_API_KEY

    Note: Deletion affects all tenants. Use with caution.
    Set force=true to delete even if model is in use (may break references).
    """
    # TODO: Check usage across ALL tenants before deletion
    # For now, we allow deletion with force parameter
    # Future enhancement: Add cross-tenant usage check

    session = container.session()
    async with session.begin():
        repo = CompletionModelsRepository(session=session)
        await repo.delete_model(id)

    return {"success": True, "message": f"Model {id} deleted successfully"}


# CRUD Operations for Embedding Models

@router.post(
    "/embedding-models/create",
    response_model=EmbeddingModelSparse,
    responses=responses.get_responses([400, 401]),
)
async def create_embedding_model(
    model_data: EmbeddingModelCreate,
    container: Container = Depends(get_container_for_sysadmin()),
) -> EmbeddingModelSparse:
    """
    Create a new embedding model (system-wide operation).

    Requires: X-API-Key header with INTRIC_SUPER_API_KEY
    """
    session = container.session()
    async with session.begin():
        repo = AdminEmbeddingModelsService(session=session)
        model = await repo.create_model(model_data)

    return model


@router.put(
    "/embedding-models/{id}/metadata",
    response_model=EmbeddingModelSparse,
    responses=responses.get_responses([404, 401]),
)
async def update_embedding_model_metadata(
    id: UUID,
    model_data: EmbeddingModelMetadataUpdate,
    container: Container = Depends(get_container_for_sysadmin()),
) -> EmbeddingModelSparse:
    """
    Update embedding model metadata (system-wide operation).

    Requires: X-API-Key header with INTRIC_SUPER_API_KEY
    """
    session = container.session()
    async with session.begin():
        repo = AdminEmbeddingModelsService(session=session)

        # Ensure model_data has the id
        update_with_id = EmbeddingModelMetadataUpdate(id=id, **model_data.model_dump(exclude={'id'}, exclude_unset=True))
        model = await repo.update_model(update_with_id)

    return model


@router.delete(
    "/embedding-models/{id}",
    responses=responses.get_responses([404, 400, 401]),
)
async def delete_embedding_model(
    id: UUID,
    force: bool = Query(False, description="Force delete even if in use"),
    container: Container = Depends(get_container_for_sysadmin()),
):
    """
    Delete an embedding model (system-wide operation).

    Requires: X-API-Key header with INTRIC_SUPER_API_KEY

    Note: Deletion affects all tenants. Use with caution.
    """
    # TODO: Add cross-tenant usage check before deletion
    # For now, we allow deletion with force parameter

    session = container.session()
    async with session.begin():
        repo = AdminEmbeddingModelsService(session=session)
        await repo.delete_model(id)

    return {"success": True, "message": f"Embedding model {id} deleted successfully"}


@router.post("/allowed-origins/", response_model=AllowedOriginInDB)
async def add_origin(
    origin: AllowedOriginCreate,
    container: Container = Depends(get_container()),
):
    allowed_origin_repo = container.allowed_origin_repo()
    return await allowed_origin_repo.add_origin(origin=origin.url, tenant_id=origin.tenant_id)


@router.get("/allowed-origins/", response_model=PaginatedResponse[AllowedOriginInDB])
async def get_origins(
    tenant_id: UUID | None = None,
    container: Container = Depends(get_container()),
):
    allowed_origin_repo = container.allowed_origin_repo()

    if tenant_id is not None:
        allowed_origins = await allowed_origin_repo.get_by_tenant(tenant_id)
    else:
        allowed_origins = await allowed_origin_repo.get_all()

    return protocol.to_paginated_response(allowed_origins)


@router.delete("/allowed-origins/{id}/", status_code=204)
async def delete_origin(
    id: UUID,
    container: Container = Depends(get_container()),
):
    allowed_origin_repo = container.allowed_origin_repo()
    await allowed_origin_repo.delete(id)


@router.post(
    "/tenants/{tenant_id}/usage-stats/recalculate",
    responses=responses.get_responses([404]),
)
async def recalculate_tenant_usage_statistics(
    tenant_id: UUID,
    container: Container = Depends(get_container_for_sysadmin()),
):
    """
    Recalculate usage statistics for a specific tenant.
    
    This endpoint is intended for tenant-specific administrative operations,
    such as fixing usage statistics for a particular tenant.
    """
    logger.info(f"Recalculating usage statistics for tenant {tenant_id}")
    
    try:
        # Use the worker task function which handles the complexity
        success = await recalculate_tenant_usage_stats_direct(container, tenant_id)
        
        if success:
            return {
                "message": f"Usage statistics recalculation completed successfully for tenant {tenant_id}",
                "tenant_id": str(tenant_id),
                "success": True
            }
        else:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail=f"Tenant {tenant_id} not found or not active"
            )
            
    except Exception as e:
        logger.error(f"Error recalculating usage statistics for tenant {tenant_id}: {str(e)}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(
            status_code=500,
            detail=f"Error recalculating usage statistics for tenant {tenant_id}: {str(e)}"
        )


@router.post(
    "/system/usage-stats/recalculate-all",
    responses=responses.get_responses([500]),
)
async def recalculate_all_tenants_usage_statistics(
    container: Container = Depends(get_container_for_sysadmin()),
):
    """
    Recalculate usage statistics for all active tenants.
    
    This endpoint is intended for system-wide administrative operations,
    such as bulk recalculation of usage statistics across all tenants.
    """
    logger.info("Recalculating usage statistics for all tenants")
    
    try:
        # Use the worker task function which handles the complexity
        from intric.worker.usage_stats_tasks import recalculate_all_tenants_usage_stats
        
        success = await recalculate_all_tenants_usage_stats(container)
        
        if success:
            return {
                "message": "Usage statistics recalculation completed successfully for all tenants",
                "success": True
            }
        else:
            return {
                "message": "Usage statistics recalculation completed with some errors",
                "success": False
            }
            
    except Exception as e:
        logger.error(f"Error in recalculate_all_tenants_usage_statistics endpoint: {str(e)}", exc_info=True)
        from fastapi import HTTPException
        raise HTTPException(
            status_code=500,
            detail=f"Error recalculating usage statistics: {str(e)}"
        )


@router.post(
    "/tenants/{tenant_id}/completion-models/{model_id}/migrate",
    response_model=MigrationResult,
    responses=responses.get_responses([400, 403, 404, 500]),
)
async def migrate_completion_model_for_tenant(
    tenant_id: UUID,
    model_id: UUID,
    migration_request: ModelMigrationRequest,
    container: Container = Depends(get_container()),
):
    """
    Migrate completion model usage for a specific tenant.
    
    This endpoint allows system administrators to migrate all usage from one 
    completion model to another for a specific tenant. This is useful for:
    - Migrating tenants away from deprecated models
    - Consolidating model usage
    - Fixing model configurations for specific tenants
    
    Args:
        tenant_id: UUID of the tenant to migrate
        model_id: UUID of the source model to migrate from
        migration_request: Details of the migration (target model, entity types, etc.)
    """
    logger.info(
        f"Starting completion model migration for tenant {tenant_id}: {model_id} -> {migration_request.to_model_id}",
        extra={
            "tenant_id": str(tenant_id),
            "from_model_id": str(model_id),
            "to_model_id": str(migration_request.to_model_id),
            "entity_types": migration_request.entity_types,
        }
    )
    
    try:
        # Get required services
        tenant_repo = container.tenant_repo()
        user_repo = container.user_repo()

        # Verify tenant exists and is active (without starting a transaction)
        session = container.session()
        tenant = await tenant_repo.get(tenant_id)
        if not tenant:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=404,
                detail=f"Tenant {tenant_id} not found"
            )

        from intric.tenants.tenant import TenantState
        if tenant.state != TenantState.ACTIVE:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Tenant {tenant_id} is not active (state: {tenant.state})"
            )

        # Get a user from this tenant to set the context (needed for domain repo)
        from intric.database.tables.users_table import Users
        from sqlalchemy import select

        stmt = select(Users).where(Users.tenant_id == tenant_id).limit(1)
        result = await session.execute(stmt)
        user_row = result.scalar_one_or_none()

        if not user_row:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"No users found for tenant {tenant_id}, cannot perform migration"
            )

        # Get the user object
        user = await user_repo.get_user_by_id(user_row.id)

        # Override container context with this user and tenant
        from dependency_injector import providers
        container.user.override(providers.Object(user))
        container.tenant.override(providers.Object(tenant))

        # Get the migration service with proper context
        migration_service = container.completion_model_migration_service()

        # Execute the migration (service will handle its own transaction)
        result = await migration_service.migrate_model_usage(
            from_model_id=model_id,
            to_model_id=migration_request.to_model_id,
            entity_types=migration_request.entity_types,
            user=user,
            confirm_migration=migration_request.confirm_migration
        )

        logger.info(
            f"Completed completion model migration for tenant {tenant_id}",
            extra={
                "tenant_id": str(tenant_id),
                "migration_id": str(result.migration_id),
                "migrated_count": result.migrated_count,
                "duration": result.duration,
            }
        )

        return result
            
    except Exception as e:
        logger.error(
            f"Error migrating completion model for tenant {tenant_id}",
            extra={
                "tenant_id": str(tenant_id),
                "from_model_id": str(model_id),
                "to_model_id": str(migration_request.to_model_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True
        )
        from fastapi import HTTPException
        raise HTTPException(
            status_code=500,
            detail=f"Error migrating completion model for tenant {tenant_id}: {str(e)}"
        )


@router.post(
    "/system/completion-models/{model_id}/migrate-all-tenants",
    response_model=dict,
    responses=responses.get_responses([400, 403, 404, 500]),
)
async def migrate_completion_model_for_all_tenants(
    model_id: UUID,
    migration_request: ModelMigrationRequest,
    container: Container = Depends(get_container()),
):
    """
    Migrate completion model usage for all active tenants.
    
    This endpoint allows system administrators to migrate all usage from one 
    completion model to another across all active tenants. This is useful for:
    - Deprecating models system-wide
    - Migrating to newer model versions
    - Consolidating model usage across the entire system
    
    Args:
        model_id: UUID of the source model to migrate from
        migration_request: Details of the migration (target model, entity types, etc.)
    """
    logger.info(
        f"Starting completion model migration for all tenants: {model_id} -> {migration_request.to_model_id}",
        extra={
            "from_model_id": str(model_id),
            "to_model_id": str(migration_request.to_model_id),
            "entity_types": migration_request.entity_types,
        }
    )
    
    try:
        # Get required services
        tenant_repo = container.tenant_repo()
        user_repo = container.user_repo()
        
        # Get all active tenants (using a separate session scope)
        tenants = await tenant_repo.get_all_tenants()
        
        from intric.tenants.tenant import TenantState
        active_tenants = [t for t in tenants if t.state == TenantState.ACTIVE]
        
        logger.info(
            f"Found {len(active_tenants)} active tenants for migration",
            extra={
                "total_tenants": len(tenants),
                "active_tenants": len(active_tenants),
                "active_tenant_ids": [str(t.id) for t in active_tenants],
            }
        )
        
        if not active_tenants:
            return {
                "message": "No active tenants found",
                "total_tenants": 0,
                "successful_migrations": 0,
                "failed_migrations": 0,
                "results": [],
            }
        
        # Process each tenant
        successful_migrations = 0
        failed_migrations = 0
        migration_results = []
        
        for tenant in active_tenants:
            try:
                logger.info(f"Processing migration for tenant {tenant.id} ({tenant.name})")
                
                # Process each tenant in its own transaction
                async with container.session().begin():
                    # Get a user from this tenant to set the context
                    from intric.database.tables.users_table import Users
                    from sqlalchemy import select
                    
                    stmt = select(Users).where(Users.tenant_id == tenant.id).limit(1)
                    result = await container.session().execute(stmt)
                    user_row = result.scalar_one_or_none()
                    
                    if not user_row:
                        logger.warning(
                            f"No users found for tenant {tenant.id}, skipping migration",
                            extra={"tenant_id": str(tenant.id), "tenant_name": tenant.name}
                        )
                        migration_results.append({
                            "tenant_id": str(tenant.id),
                            "tenant_name": tenant.name,
                            "success": False,
                            "error": "No users found for tenant",
                            "migrated_count": 0,
                        })
                        failed_migrations += 1
                        continue
                    
                    # Get the user object
                    user = await user_repo.get_user_by_id(user_row.id)
                    
                    # Override container context with this user and tenant
                    from dependency_injector import providers
                    container.user.override(providers.Object(user))
                    container.tenant.override(providers.Object(tenant))
                    
                    # Get the migration service with proper context
                    migration_service = container.completion_model_migration_service()
                    
                    # Execute the migration
                    result = await migration_service.migrate_model_usage(
                        from_model_id=model_id,
                        to_model_id=migration_request.to_model_id,
                        entity_types=migration_request.entity_types,
                        user=user,
                        confirm_migration=migration_request.confirm_migration
                    )
                    
                    successful_migrations += 1
                    migration_results.append({
                        "tenant_id": str(tenant.id),
                        "tenant_name": tenant.name,
                        "success": True,
                        "migration_id": str(result.migration_id),
                        "migrated_count": result.migrated_count,
                        "duration": result.duration,
                        "warnings": result.warnings,
                    })
                    
                    logger.info(
                        f"Successfully completed migration for tenant {tenant.id}",
                        extra={
                            "tenant_id": str(tenant.id),
                            "tenant_name": tenant.name,
                            "migration_id": str(result.migration_id),
                            "migrated_count": result.migrated_count,
                        }
                    )
                    
            except Exception as e:
                logger.error(
                    f"Error migrating completion model for tenant {tenant.id}",
                    extra={
                        "tenant_id": str(tenant.id),
                        "tenant_name": getattr(tenant, 'name', 'unknown'),
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                    exc_info=True
                )
                failed_migrations += 1
                migration_results.append({
                    "tenant_id": str(tenant.id),
                    "tenant_name": getattr(tenant, 'name', 'unknown'),
                    "success": False,
                    "error": str(e),
                    "migrated_count": 0,
                })
                continue
        
        logger.info(
            "Completed completion model migration for all tenants",
            extra={
                "total_tenants": len(active_tenants),
                "successful_migrations": successful_migrations,
                "failed_migrations": failed_migrations,
                "from_model_id": str(model_id),
                "to_model_id": str(migration_request.to_model_id),
            }
        )
        
        return {
            "message": f"Migration completed for {successful_migrations} out of {len(active_tenants)} tenants",
            "total_tenants": len(active_tenants),
            "successful_migrations": successful_migrations,
            "failed_migrations": failed_migrations,
            "results": migration_results,
        }
        
    except Exception as e:
        logger.error(
            "Error in migrate_completion_model_for_all_tenants endpoint",
            extra={
                "from_model_id": str(model_id),
                "to_model_id": str(migration_request.to_model_id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True
        )
        from fastapi import HTTPException
        raise HTTPException(
            status_code=500,
            detail=f"Error migrating completion model for all tenants: {str(e)}"
        )
