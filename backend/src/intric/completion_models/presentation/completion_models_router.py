# MIT License

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.completion_models.presentation import (
    CompletionModelPublic,
    CompletionModelUpdateFlags,
)
from intric.roles.permissions import Permission, validate_permission
from intric.completion_models.presentation.completion_model_models import (
    ModelUsageStatistics,
    ModelUsageDetail,
    ModelMigrationRequest,
    MigrationResult,
    ModelUsageSummary,
    ModelMigrationHistory,
    PaginatedResponse as ModelUsagePaginatedResponse,
)
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container
from intric.authentication.auth_dependencies import get_current_active_user
from intric.server.protocol import responses
from intric.users.user import UserInDB

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[CompletionModelPublic],
)
async def get_completion_models(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.completion_model_crud_service()
    assembler = container.completion_model_assembler()

    models = await service.get_completion_models()

    return assembler.from_completion_models_to_models(models)


@router.post(
    "/{id}/",
    response_model=CompletionModelPublic,
    responses=responses.get_responses([404]),
)
async def update_completion_model(
    id: UUID,
    update_flags: CompletionModelUpdateFlags,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.completion_model_crud_service()
    assembler = container.completion_model_assembler()

    completion_model = await service.update_completion_model(
        model_id=id,
        is_org_enabled=update_flags.is_org_enabled,
        is_org_default=update_flags.is_org_default,
        security_classification=update_flags.security_classification,
    )

    return assembler.from_completion_model_to_model(completion_model=completion_model)


@router.get(
    "/{model_id}/usage",
    response_model=ModelUsageStatistics,
    responses=responses.get_responses([404]),
)
async def get_model_usage(
    model_id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> ModelUsageStatistics:
    """Get usage statistics for a specific model (pre-aggregated for performance)"""
    service = container.completion_model_usage_service()
    return await service.get_model_usage_statistics(model_id, user.tenant_id)


@router.get(
    "/{model_id}/usage/details",
    response_model=ModelUsagePaginatedResponse,
    responses=responses.get_responses([404]),
)
async def get_model_usage_details(
    model_id: UUID,
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    cursor: Optional[str] = Query(None, description="Cursor for pagination"),
    limit: int = Query(default=50, le=100, description="Number of results per page"),
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> ModelUsagePaginatedResponse:
    """Get detailed list of entities using this model with cursor pagination"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(
        f"Starting get_model_usage_details endpoint",
        extra={
            "model_id": str(model_id),
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "entity_type": entity_type,
            "cursor": cursor,
            "limit": limit,
        }
    )
    
    try:
        # Get the service and verify container is properly configured
        logger.debug("Getting completion_model_usage_service from container")
        service = container.completion_model_usage_service()
        logger.debug(f"Got service instance: {type(service)}")
        
        # Validate inputs
        if not model_id:
            logger.error("Model ID is required but was None")
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Model ID is required")
        
        if not user.tenant_id:
            logger.error("User tenant_id is required but was None")
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="User tenant_id is required")
        
        # Call the service method
        logger.info("Calling service.get_model_usage_details")
        result = await service.get_model_usage_details(
            model_id, user.tenant_id, entity_type, cursor, limit
        )
        
        logger.info(
            f"Successfully retrieved model usage details",
            extra={
                "model_id": str(model_id),
                "tenant_id": str(user.tenant_id),
                "results_count": len(result.items) if result and result.items else 0,
                "has_more": result.has_more if result else False,
                "total": result.total if result else 0,
            }
        )
        
        return result
        
    except Exception as e:
        logger.error(
            f"Error in get_model_usage_details endpoint",
            extra={
                "model_id": str(model_id),
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "entity_type": entity_type,
                "cursor": cursor,
                "limit": limit,
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True
        )
        # Re-raise to let FastAPI handle the error response
        raise


@router.post(
    "/{model_id}/migrate",
    response_model=MigrationResult,
    responses=responses.get_responses([400, 403, 404]),
)
async def migrate_model_usage(
    model_id: UUID,
    migration_request: ModelMigrationRequest,
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> MigrationResult:
    """Migrate all usage from one model to another with safety checks"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(
        f"Starting migrate_model_usage endpoint",
        extra={
            "from_model_id": str(model_id),
            "to_model_id": str(migration_request.to_model_id),
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "entity_types": migration_request.entity_types,
            "confirm_migration": migration_request.confirm_migration,
        }
    )
    
    try:
        # Get the service and verify container is properly configured
        logger.debug("Getting completion_model_migration_service from container")
        migration_service = container.completion_model_migration_service()
        logger.debug(f"Got migration service instance: {type(migration_service)}")
        
        # Validate inputs
        if not model_id:
            logger.error("From model ID is required but was None")
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="From model ID is required")
        
        if not migration_request.to_model_id:
            logger.error("To model ID is required but was None")
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="To model ID is required")
        
        if model_id == migration_request.to_model_id:
            logger.error("From and to model IDs cannot be the same")
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="From and to model IDs cannot be the same")
        
        if not user.tenant_id:
            logger.error("User tenant_id is required but was None")
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="User tenant_id is required")
        
        # Validate admin permissions
        validate_permission(user, Permission.ADMIN)
        
        # Call the service method
        logger.info("Calling migration_service.migrate_model_usage")
        result = await migration_service.migrate_model_usage(
            from_model_id=model_id,
            to_model_id=migration_request.to_model_id,
            entity_types=migration_request.entity_types,
            user=user,
            confirm_migration=migration_request.confirm_migration,
        )
        
        logger.info(
            f"Successfully completed model migration",
            extra={
                "from_model_id": str(model_id),
                "to_model_id": str(migration_request.to_model_id),
                "tenant_id": str(user.tenant_id),
                "migration_id": str(result.migration_id),
                "migrated_count": result.migrated_count,
                "failed_count": result.failed_count,
                "duration": result.duration,
                "success": result.success,
                "warnings": result.warnings,
            }
        )
        
        return result
        
    except Exception as e:
        logger.error(
            f"Error in migrate_model_usage endpoint",
            extra={
                "from_model_id": str(model_id),
                "to_model_id": str(migration_request.to_model_id),
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "entity_types": migration_request.entity_types,
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True
        )
        # Re-raise to let FastAPI handle the error response
        raise


@router.get(
    "/usage-summary",
    response_model=List[ModelUsageSummary],
)
async def get_all_models_usage_summary(
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> List[ModelUsageSummary]:
    """Get usage summary for all models (optimized with pre-aggregation)"""
    try:
        service = container.completion_model_usage_service()
        return await service.get_all_models_usage_summary(user.tenant_id)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            f"Error in get_all_models_usage_summary endpoint",
            extra={
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        # Re-raise to let FastAPI handle the error response
        raise


@router.get(
    "/{model_id}/migration-history",
    response_model=List[ModelMigrationHistory],
    responses=responses.get_responses([404]),
)
async def get_model_migration_history(
    model_id: UUID,
    limit: int = Query(default=50, le=100, description="Number of results per page"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> List[ModelMigrationHistory]:
    """Get migration history for a specific model (from or to this model)"""
    service = container.completion_model_migration_history_service()
    return await service.get_migration_history_for_model(
        model_id, user.tenant_id, limit, offset
    )


@router.get(
    "/migration-history",
    response_model=List[ModelMigrationHistory],
)
async def get_all_migration_history(
    limit: int = Query(default=50, le=100, description="Number of results per page"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> List[ModelMigrationHistory]:
    """Get all migration history for the tenant"""
    service = container.completion_model_migration_history_service()
    return await service.get_migration_history_for_tenant(
        user.tenant_id, limit, offset
    )


@router.get(
    "/migration-history/{migration_id}",
    response_model=ModelMigrationHistory,
    responses=responses.get_responses([404]),
)
async def get_migration_history_by_id(
    migration_id: UUID,
    user: UserInDB = Depends(get_current_active_user),
    container: Container = Depends(get_container(with_user=True)),
) -> ModelMigrationHistory:
    """Get a specific migration history record by ID"""
    service = container.completion_model_migration_history_service()
    history = await service.get_migration_history_by_id(migration_id, user.tenant_id)
    
    if not history:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Migration history not found")
    
    return history
