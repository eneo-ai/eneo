from intric.jobs.task_models import Transcription, UploadInfoBlob
from intric.main.container.container import Container
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.worker.crawl_tasks import crawl_task, queue_website_crawls
from intric.worker.upload_tasks import transcription_task, upload_info_blob_task
from intric.worker.worker import Worker
from intric.worker.usage_stats_tasks import (
    update_model_usage_stats_task,
    recalculate_all_tenants_usage_stats,
    recalculate_tenant_usage_stats,
)
from intric.audit.application.audit_worker_task import log_audit_event_task

worker = Worker()


@worker.function()
async def upload_info_blob(job_id: str, params: UploadInfoBlob, container: Container):
    return await upload_info_blob_task(
        job_id=job_id, params=params, container=container
    )


@worker.function()
async def transcription(job_id: str, params: Transcription, container: Container):
    return await transcription_task(job_id=job_id, params=params, container=container)


@worker.function()
async def crawl(job_id: str, params: CrawlTask, container: Container):
    return await crawl_task(job_id=job_id, params=params, container=container)


@worker.cron_job(
    minute=0
)  # Hourly at :00 - enables true ~24h scheduling for DAILY websites
async def crawl_all_websites(container: Container):
    """Hourly cron job to check and queue websites based on their update intervals.

    Why: Hourly checks ensure DAILY websites are scheduled ~24 hours after last crawl,
    not up to ~39 hours with single daily cron. Query is fast (indexed) and lightweight.

    Schedule handles:
    - DAILY: ~24 hours after last crawl
    - EVERY_OTHER_DAY: ~48 hours after last crawl
    - WEEKLY: Fridays only, ~7 days after last crawl
    - NEVER: Skipped
    """
    return await queue_website_crawls(container=container)


@worker.function()
async def update_model_usage_stats(job_id: str, params: dict, container: Container):
    """Worker function for updating model usage statistics.

    Note: params is a dict here because it comes from ARQ, but we validate it
    by creating UpdateUsageStatsTaskParams inside the task function.
    """
    return await update_model_usage_stats_task(
        job_id=job_id, params=params, container=container
    )


@worker.function(with_user=False)
async def recalculate_tenant_usage_stats_job(job_id: str, params: dict, container: Container):
    """Worker function for recalculating usage statistics for a specific tenant.

    Args:
        job_id: ARQ job ID
        params: Dictionary containing tenant_id
        container: Dependency injection container
    """
    from uuid import UUID

    # Extract tenant_id from params
    tenant_id = UUID(params["tenant_id"])

    return await recalculate_tenant_usage_stats(
        container=container, tenant_id=tenant_id
    )


@worker.cron_job(hour=19, minute=00)  # Daily at 02:00 UTC
async def recalculate_usage_stats(container: Container):
    """Nightly recalculation of all tenant usage statistics"""
    return await recalculate_all_tenants_usage_stats(container=container)


@worker.function(with_user=False)
async def log_audit_event(job_id: str, params: dict, container: Container):
    """Worker function for async audit logging.

    Args:
        job_id: ARQ job ID
        params: Audit log parameters (dict)
        container: Dependency injection container

    Returns:
        Dictionary with audit_log_id
    """
    session = container.session()
    return await log_audit_event_task(job_id=job_id, params=params, session=session)


@worker.cron_job(hour=2, minute=0)  # Daily at 02:00 UTC
async def purge_old_audit_logs(container: Container):
    """
    Daily cron job to purge old audit logs based on retention policies.

    Runs at 02:00 UTC (3:00 AM Swedish time) to minimize user impact.

    CRITICAL: Each tenant is processed in a SEPARATE database session/transaction.
    This ensures:
    - Tenant A's failure doesn't rollback Tenant B's successful deletion
    - Each tenant's retention policy is applied independently
    - True multi-tenant isolation with no cross-tenant interference

    For each tenant (in isolated transactions):
    - Retrieves retention policy (default: 365 days)
    - PERMANENTLY DELETES logs older than retention period (hard delete)
    - Updates purge statistics
    - Commits independently (failures don't affect other tenants)

    Note: Deleted logs cannot be recovered. This ensures compliance with
    data retention regulations that require true deletion.

    Returns:
        Dictionary with purge statistics per tenant and any errors
    """
    from uuid import UUID

    from sqlalchemy import select

    from intric.audit.application.retention_service import RetentionService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.actor_types import ActorType
    from intric.audit.domain.entity_types import EntityType
    from intric.database.database import sessionmanager
    from intric.database.tables.audit_retention_policy_table import AuditRetentionPolicy
    from intric.main.logging import get_logger

    logger = get_logger(__name__)

    # Step 1: Get all tenant IDs with retention policies
    # Uses the container's session (provided by cron_job decorator) for read-only query
    session = container.session()
    query = select(AuditRetentionPolicy.tenant_id)
    result = await session.execute(query)
    tenant_ids: list[UUID] = list(result.scalars().all())

    logger.info(f"Starting audit log retention purge for {len(tenant_ids)} tenants")

    # Step 2: Process each tenant in its own ISOLATED session/transaction
    # CRITICAL: Using sessionmanager.session() creates a NEW session per tenant
    # This ensures true transaction isolation - one tenant's failure won't affect others
    purge_stats: dict[str, dict] = {}
    errors: list[dict] = []

    for tenant_id in tenant_ids:
        tenant_id_str = str(tenant_id)

        try:
            # NEW session per tenant = true transaction isolation
            # If this tenant fails, only this transaction rolls back
            async with sessionmanager.session() as tenant_session, tenant_session.begin():
                retention_service = RetentionService(tenant_session)

                # Get THIS tenant's retention policy and purge ONLY their old logs
                # The DELETE query filters by tenant_id, ensuring no cross-tenant deletion
                purged_count = await retention_service.purge_old_logs(tenant_id)

                # Get retention days for statistics
                policy = await retention_service.get_policy(tenant_id)

                purge_stats[tenant_id_str] = {
                    "retention_days": policy.retention_days,
                    "purged_count": purged_count,
                }

                # Create audit log entry for this tenant if logs were purged
                # Note: Using log_async queues to ARQ, doesn't block this transaction
                if purged_count > 0:
                    # Import AuditService here to avoid circular imports
                    from intric.audit.application.audit_service import AuditService
                    from intric.audit.infrastructure.audit_log_repo_impl import (
                        AuditLogRepositoryImpl,
                    )

                    audit_repo = AuditLogRepositoryImpl(tenant_session)
                    audit_service = AuditService(
                        repository=audit_repo,
                        session=tenant_session,
                        redis=container.redis(),
                    )
                    await audit_service.log_async(
                        tenant_id=tenant_id,
                        actor_id=tenant_id,  # System actor
                        actor_type=ActorType.SYSTEM,
                        action=ActionType.RETENTION_POLICY_APPLIED,
                        entity_type=EntityType.TENANT_SETTINGS,
                        entity_id=tenant_id,
                        description=f"Retention policy purged {purged_count} audit logs",
                        metadata={
                            "actor": {"type": "system", "via": "cron_job"},
                            "target": {
                                "tenant_id": tenant_id_str,
                                "purged_count": purged_count,
                                "retention_days": policy.retention_days,
                            },
                        },
                    )

                    logger.debug(
                        f"Purged {purged_count} audit logs for tenant {tenant_id_str} "
                        f"(retention: {policy.retention_days} days)"
                    )

            # Transaction committed successfully for this tenant

        except Exception as e:
            # This tenant's transaction rolled back, but others continue
            error_info = {
                "tenant_id": tenant_id_str,
                "error": str(e),
            }
            errors.append(error_info)
            logger.error(
                f"Failed to purge audit logs for tenant {tenant_id_str}: {e}",
                exc_info=True,
            )
            # Continue to next tenant - isolation ensures this failure doesn't affect others

    # Step 3: Log summary
    total_purged = sum(stats["purged_count"] for stats in purge_stats.values())
    total_tenants = len(purge_stats)
    failed_tenants = len(errors)

    if failed_tenants > 0:
        logger.warning(
            f"Audit log retention purge completed with errors: "
            f"{total_tenants} tenants processed, {failed_tenants} failed, "
            f"{total_purged} total logs purged",
            extra={
                "total_tenants": total_tenants,
                "failed_tenants": failed_tenants,
                "total_purged": total_purged,
                "errors": errors,
            },
        )
    else:
        logger.info(
            "Audit log retention purge completed successfully",
            extra={
                "total_tenants": total_tenants,
                "total_purged": total_purged,
                "purge_stats": purge_stats,
            },
        )

    return {
        "purge_stats": purge_stats,
        "errors": errors,
        "total_tenants": total_tenants,
        "total_purged": total_purged,
        "success": len(errors) == 0,
    }
