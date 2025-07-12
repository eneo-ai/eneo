"""Background tasks for completion model usage statistics updates."""

import logging
from uuid import UUID

from dependency_injector import providers
from intric.completion_models.application.completion_model_usage_service import (
    CompletionModelUsageService,
)
from intric.events import ModelUsageStatsUpdated, get_event_publisher
from intric.jobs.job_models import Task
from intric.jobs.task_models import UpdateUsageStatsTaskParams
from intric.main.container.container import Container

logger = logging.getLogger(__name__)


async def update_model_usage_stats_task(
    *,
    job_id: UUID,
    params: dict,
    container: Container,
):
    """Update pre-aggregated usage statistics for a tenant.
    
    Args:
        job_id: The job ID for tracking
        params: Dictionary containing task parameters
        container: Dependency injection container
    """
    logger.info(f"Starting update_model_usage_stats_task with job_id={job_id}, params={params}")
    
    task_manager = container.task_manager(job_id=job_id)
    
    async with task_manager.set_status_on_exception():
        # Validate parameters using Pydantic model
        try:
            validated_params = UpdateUsageStatsTaskParams(**params)
            logger.info(f"Validated params: {validated_params}")
        except Exception as e:
            logger.error(f"Failed to validate params {params}: {e}", exc_info=True)
            raise
        
        tenant_id = validated_params.tenant_id
        model_id = validated_params.model_id
        full_recalc = validated_params.full_recalc
        
        logger.info(f"Processing tenant_id={tenant_id}, model_id={model_id}, full_recalc={full_recalc}")
        
        # Get the usage service from container
        usage_service = container.completion_model_usage_service()
        event_publisher = get_event_publisher()
        
        try:
            if full_recalc:
                # Full recalculation (scheduled nightly)
                logger.info(
                    f"Starting full usage statistics recalculation for tenant {tenant_id}",
                    extra={
                        "tenant_id": str(tenant_id),
                        "job_id": str(job_id),
                        "operation": "full_recalc"
                    }
                )
                
                # Add debugging to the service call
                logger.debug(f"Calling usage_service.recalculate_all_usage_stats for tenant {tenant_id}")
                result = await usage_service.recalculate_all_usage_stats(tenant_id)
                logger.info(f"recalculate_all_usage_stats returned: {result}")
                
                update_type = "full"
            else:
                # Incremental update (triggered by entity changes)
                logger.info(
                    f"Starting incremental usage statistics update for tenant {tenant_id}",
                    extra={
                        "tenant_id": str(tenant_id),
                        "model_id": str(model_id) if model_id else "all",
                        "job_id": str(job_id),
                        "operation": "incremental_update"
                    }
                )
                
                # Add debugging to the service call
                logger.debug(f"Calling usage_service.update_usage_stats_incremental for tenant {tenant_id}, model {model_id}")
                result = await usage_service.update_usage_stats_incremental(tenant_id, model_id)
                logger.info(f"update_usage_stats_incremental returned: {result}")
                
                update_type = "incremental"
            
            # Publish domain event
            logger.debug(f"Publishing ModelUsageStatsUpdated event for tenant {tenant_id}")
            await event_publisher.publish(
                ModelUsageStatsUpdated(
                    model_id=model_id,  # Can be None for "all models"
                    tenant_id=tenant_id,
                    update_type=update_type,
                )
            )
            
            logger.info(
                f"Completed usage statistics update for tenant {tenant_id}",
                extra={
                    "tenant_id": str(tenant_id),
                    "model_id": str(model_id) if model_id else "all",
                    "job_id": str(job_id),
                    "update_type": update_type,
                    "operation": "usage_stats_update"
                }
            )
            
            task_manager.result_location = f"/api/v1/admin/models/usage-summary?tenant_id={tenant_id}"
            
        except Exception as e:
            logger.error(
                f"Failed to update usage statistics for tenant {tenant_id}",
                extra={
                    "tenant_id": str(tenant_id),
                    "model_id": str(model_id) if model_id else "all",
                    "job_id": str(job_id),
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "operation": "usage_stats_update"
                },
                exc_info=True
            )
            raise
    
    logger.info(f"update_model_usage_stats_task completed successfully for job {job_id}")
    return task_manager.successful()


async def recalculate_tenant_usage_stats(container: Container, tenant_id: UUID):
    """Recalculate usage statistics for a specific tenant.
    
    This is designed to be called from admin panel for tenant-specific operations.
    
    Args:
        container: Dependency injection container
        tenant_id: UUID of the tenant to recalculate usage stats for
    """
    logger.info(
        f"Starting usage statistics recalculation for tenant {tenant_id}",
        extra={"tenant_id": str(tenant_id)}
    )
    
    tenant_repo = container.tenant_repo()
    
    # Get the specific tenant and verify it exists and is active
    async with container.session().begin():
        tenant = await tenant_repo.get(tenant_id)
        if not tenant:
            logger.error(
                f"Tenant {tenant_id} not found",
                extra={"tenant_id": str(tenant_id)}
            )
            return False
            
        # Import TenantState to check for active status
        from intric.tenants.tenant import TenantState
        if tenant.state != TenantState.ACTIVE:
            logger.warning(
                f"Tenant {tenant_id} is not active (state: {tenant.state}), skipping usage stats recalculation",
                extra={"tenant_id": str(tenant_id), "tenant_state": tenant.state}
            )
            return False
    
    # Get job service for queuing tasks
    job_service = container.job_service()
    
    try:
        # Create task parameters
        task_params = UpdateUsageStatsTaskParams(
            user_id=UUID("00000000-0000-0000-0000-000000000000"),  # System user for cron jobs
            tenant_id=tenant_id,
            full_recalc=True
        )
        
        # Queue the background task
        await job_service.queue_job(
            Task.UPDATE_MODEL_USAGE_STATS,
            name=f"Usage stats recalculation for tenant {tenant_id}",
            task_params=task_params,
        )
        
        logger.info(
            f"Successfully queued usage statistics recalculation for tenant {tenant_id}",
            extra={"tenant_id": str(tenant_id)}
        )
        
        return True
        
    except Exception as e:
        logger.error(
            f"Error queuing usage stats update for tenant {tenant_id}",
            extra={
                "tenant_id": str(tenant_id),
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        return False

async def recalculate_tenant_usage_stats_direct(container: Container, tenant_id: UUID):
    """Recalculate usage statistics for a specific tenant directly (for sysadmin endpoints).
    
    This function performs the recalculation synchronously without using the job service,
    making it suitable for sysadmin endpoints that need immediate execution.
    
    Args:
        container: Dependency injection container (without user dependency)
        tenant_id: UUID of the tenant to recalculate usage stats for
    """
    logger.info(
        f"Starting direct usage statistics recalculation for tenant {tenant_id}",
        extra={"tenant_id": str(tenant_id)}
    )
    
    tenant_repo = container.tenant_repo()
    user_repo = container.user_repo()
    
    # Get the specific tenant and verify it exists and is active
    async with container.session().begin():
        tenant = await tenant_repo.get(tenant_id)
        if not tenant:
            logger.error(
                f"Tenant {tenant_id} not found",
                extra={"tenant_id": str(tenant_id)}
            )
            return False
            
        # Import TenantState to check for active status
        from intric.tenants.tenant import TenantState
        if tenant.state != TenantState.ACTIVE:
            logger.warning(
                f"Tenant {tenant_id} is not active (state: {tenant.state}), skipping usage stats recalculation",
                extra={"tenant_id": str(tenant_id), "tenant_state": tenant.state}
            )
            return False
        
        # Get a user from this tenant to set the context (needed for domain repo)
        from intric.database.tables.users_table import Users
        from sqlalchemy import select
        
        stmt = select(Users).where(Users.tenant_id == tenant_id).limit(1)
        result = await container.session().execute(stmt)
        user_row = result.scalar_one_or_none()
        
        if not user_row:
            logger.error(
                f"No users found for tenant {tenant_id}, cannot perform recalculation",
                extra={"tenant_id": str(tenant_id)}
            )
            return False
        
        # Get the user object
        user = await user_repo.get_user_by_id(user_row.id)
        
        # Override container context with this user and tenant
        from dependency_injector import providers
        container.user.override(providers.Object(user))
        container.tenant.override(providers.Object(tenant))
        
        # Get the usage service with proper context
        usage_service = container.completion_model_usage_service()
        
        # Perform full recalculation within the existing transaction
        logger.info(f"Starting direct recalculation for tenant {tenant_id}")
        await usage_service.recalculate_all_usage_stats_in_transaction(tenant_id)
        
        logger.info(
            f"Successfully completed direct usage stats recalculation for tenant {tenant_id}",
            extra={"tenant_id": str(tenant_id)}
        )
        
        return True

async def recalculate_all_tenants_usage_stats(container: Container):
    """Recalculate usage statistics for all active tenants.
    
    This is designed to be called from a cron job for nightly updates.
    """
    logger.info("Starting nightly usage statistics recalculation for all tenants")
    
    tenant_repo = container.tenant_repo()
    user_repo = container.user_repo()
    
    # Get all active tenants first (in a read-only transaction)
    async with container.session().begin():
        tenants = await tenant_repo.get_all_tenants()
        logger.info(f"Found {len(tenants)} total tenants from database")
        
        # Import TenantState to filter for active tenants
        from intric.tenants.tenant import TenantState
        active_tenants = [t for t in tenants if t.state == TenantState.ACTIVE]
        
        # Log tenant states for debugging
        for tenant in tenants:
            logger.info(
                f"Tenant {tenant.id} ({tenant.name}): state={tenant.state}, active={tenant.state == TenantState.ACTIVE}",
                extra={
                    "tenant_id": str(tenant.id),
                    "tenant_name": tenant.name,
                    "tenant_state": tenant.state,
                    "is_active": tenant.state == TenantState.ACTIVE
                }
            )
        
        logger.info(
            f"Found {len(active_tenants)} active tenants for usage stats update",
            extra={"tenant_count": len(active_tenants), "active_tenant_ids": [str(t.id) for t in active_tenants]}
        )
        
        if not active_tenants:
            logger.warning("No active tenants found, skipping usage stats recalculation")
            return True
    
    # Process each tenant in its own transaction to avoid unique constraint violations
    processed_count = 0
    for tenant in active_tenants:
        try:
            logger.info(f"Processing usage stats for tenant {tenant.id} ({tenant.name})")
            
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
                        f"No users found for tenant {tenant.id}, skipping usage stats recalculation",
                        extra={"tenant_id": str(tenant.id), "tenant_name": tenant.name}
                    )
                    continue
                
                # Get the user object
                user = await user_repo.get_user_by_id(user_row.id)
                
                # Override container context with this user and tenant
                container.user.override(providers.Object(user))
                container.tenant.override(providers.Object(tenant))
                
                # Get the usage service with proper context
                usage_service = container.completion_model_usage_service()
                
                # Perform full recalculation
                logger.info(f"Starting full recalculation for tenant {tenant.id}")
                await usage_service.recalculate_all_usage_stats_in_transaction(tenant.id)
                
                processed_count += 1
                
                logger.info(
                    f"Successfully completed usage stats recalculation for tenant {tenant.id}",
                    extra={
                        "tenant_id": str(tenant.id),
                        "tenant_name": tenant.name,
                        "processed_count": processed_count
                    }
                )
                
        except Exception as e:
            logger.error(
                f"Error processing usage stats for tenant {tenant.id}",
                extra={
                    "tenant_id": str(tenant.id),
                    "tenant_name": getattr(tenant, 'name', 'unknown'),
                    "error": str(e),
                    "error_type": type(e).__name__
                },
                exc_info=True
            )
            # Continue processing other tenants even if one fails
            continue
    
    logger.info(
        f"Completed processing: {processed_count} out of {len(active_tenants)} tenants successfully processed",
        extra={"processed_count": processed_count, "total_active_tenants": len(active_tenants)}
    )
    
    return True