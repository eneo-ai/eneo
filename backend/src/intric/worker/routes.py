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
from intric.audit.application.export_worker_task import export_audit_logs_task

worker = Worker()


@worker.function()
async def upload_info_blob(job_id: str, params: UploadInfoBlob, container: Container):
    return await upload_info_blob_task(
        job_id=job_id, params=params, container=container
    )


@worker.function()
async def transcription(job_id: str, params: Transcription, container: Container):
    return await transcription_task(job_id=job_id, params=params, container=container)


@worker.long_running_function()
async def crawl(job_id: str, params: CrawlTask, container: Container):
    """Crawl task uses long_running_function to avoid DB pool exhaustion.

    Unlike regular worker.function(), this:
    1. Uses short-lived bootstrap session for user lookup (~50ms)
    2. Runs with sessionless container (no connection held)
    3. crawl_task manages its own sessions via Container.session_scope()

    This prevents holding a DB connection for the entire crawl (5-30 minutes).
    """
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
async def recalculate_tenant_usage_stats_job(
    job_id: str, params: dict, container: Container
):
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


@worker.function(with_user=False)
async def export_audit_logs(job_id: str, params: dict, container: Container):
    """Worker function for async audit log export.

    Exports audit logs to file with progress tracking and cancellation support.
    Uses streaming for constant memory usage regardless of dataset size.

    Args:
        job_id: ARQ job ID (also used as export job ID)
        params: Export parameters (dict) - validated as AuditExportTaskParams
        container: Dependency injection container

    Returns:
        Dictionary with export result (job_id, status, file_path, etc.)
    """
    session = container.session()
    redis = container.redis_client()
    return await export_audit_logs_task(
        job_id=job_id, params=params, session=session, redis=redis
    )


@worker.cron_job(hour=3, minute=0)  # Daily at 03:00 UTC
async def cleanup_old_exports(container: Container):
    """Daily cron job to clean up old export files.

    Runs at 03:00 UTC (4:00 AM Swedish winter, 5:00 AM summer) to minimize user impact.
    Scheduled after audit log purge to avoid worker overload.

    Removes:
    - Export files older than export_max_age_hours (default: 24 hours)
    - Corresponding Redis job keys

    Returns:
        Dictionary with cleanup statistics
    """
    import os
    from datetime import datetime, timezone

    from intric.audit.infrastructure.export_job_manager import ExportJobManager
    from intric.main.config import get_settings
    from intric.main.logging import get_logger

    logger = get_logger(__name__)
    settings = get_settings()

    logger.info("Starting export file cleanup")

    redis = container.redis_client()
    job_manager = ExportJobManager(redis)

    # Get expired jobs from Redis
    expired_jobs = await job_manager.get_expired_jobs()

    files_deleted = 0
    bytes_freed = 0
    jobs_cleaned = 0
    errors = []

    for job in expired_jobs:
        try:
            # Delete file if it exists
            if job.file_path and os.path.exists(job.file_path):
                file_size = os.path.getsize(job.file_path)
                os.remove(job.file_path)
                files_deleted += 1
                bytes_freed += file_size
                logger.debug(
                    f"Deleted export file: {job.file_path} ({file_size} bytes)"
                )

            # Delete Redis key
            await job_manager.delete_job(job.tenant_id, job.job_id)
            jobs_cleaned += 1

        except Exception as e:
            errors.append(
                {
                    "job_id": str(job.job_id),
                    "tenant_id": str(job.tenant_id),
                    "error": str(e),
                }
            )
            logger.warning(f"Failed to clean up export job {job.job_id}: {e}")

    # Also clean up any orphaned files (files without Redis entries)
    # This handles edge cases where Redis key expired but file remained
    export_dir = settings.export_dir
    if export_dir.exists():
        now = datetime.now(timezone.utc)
        max_age_seconds = settings.export_max_age_hours * 3600

        for tenant_dir in export_dir.iterdir():
            if not tenant_dir.is_dir():
                continue

            for file_path in tenant_dir.iterdir():
                if not file_path.is_file():
                    continue

                try:
                    # Check file age
                    file_mtime = datetime.fromtimestamp(
                        file_path.stat().st_mtime, tz=timezone.utc
                    )
                    age_seconds = (now - file_mtime).total_seconds()

                    if age_seconds > max_age_seconds:
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        files_deleted += 1
                        bytes_freed += file_size
                        logger.debug(
                            f"Deleted orphaned export file: {file_path} ({file_size} bytes)"
                        )
                except Exception as e:
                    errors.append(
                        {
                            "file_path": str(file_path),
                            "error": str(e),
                        }
                    )

            # Remove empty tenant directories
            try:
                if tenant_dir.is_dir() and not any(tenant_dir.iterdir()):
                    tenant_dir.rmdir()
            except Exception:
                pass  # Ignore errors removing empty directories

    if errors:
        logger.warning(
            f"Export cleanup completed with {len(errors)} errors",
            extra={
                "files_deleted": files_deleted,
                "bytes_freed": bytes_freed,
                "jobs_cleaned": jobs_cleaned,
                "errors": errors,
            },
        )
    else:
        logger.info(
            "Export cleanup completed",
            extra={
                "files_deleted": files_deleted,
                "bytes_freed": bytes_freed,
                "jobs_cleaned": jobs_cleaned,
            },
        )

    return {
        "files_deleted": files_deleted,
        "bytes_freed": bytes_freed,
        "jobs_cleaned": jobs_cleaned,
        "errors": errors,
        "success": len(errors) == 0,
    }


@worker.cron_job(hour=2, minute=0)  # Daily at 02:00 UTC
async def purge_old_audit_logs(container: Container):
    """
    Daily cron job to purge old audit logs based on retention policies.

    Runs at 02:00 UTC (3:00 AM Swedish winter, 4:00 AM summer) to minimize user impact.
    Scheduled 2 hours after website crawls to avoid worker overload.

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

    from intric.audit.application.audit_config_service import AuditConfigService
    from intric.audit.application.retention_service import RetentionService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.actor_types import ActorType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_config_repository import (
        AuditConfigRepositoryImpl,
    )
    from intric.database.database import sessionmanager
    from intric.database.tables.tenant_table import Tenants
    from intric.feature_flag.feature_flag_repo import FeatureFlagRepository
    from intric.feature_flag.feature_flag_service import FeatureFlagService
    from intric.main.logging import get_logger

    logger = get_logger(__name__)

    # Step 1: Get all tenant IDs (retention policy will be created if missing)
    # Uses the container's session (provided by cron_job decorator) for read-only query
    session = container.session()
    query = select(Tenants.id)
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
            async with (
                sessionmanager.session() as tenant_session,
                tenant_session.begin(),
            ):
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
                    audit_config_repo = AuditConfigRepositoryImpl(tenant_session)
                    audit_config_service = AuditConfigService(audit_config_repo)
                    feature_flag_repo = FeatureFlagRepository(tenant_session)
                    feature_flag_service = FeatureFlagService(feature_flag_repo)
                    audit_service = AuditService(
                        repository=audit_repo,
                        audit_config_service=audit_config_service,
                        feature_flag_service=feature_flag_service,
                    )
                    await audit_service.log_async(
                        tenant_id=tenant_id,
                        actor_id=None,  # System actor (no user)
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
    total_tenants = len(tenant_ids)
    successful_tenants = len(purge_stats)
    failed_tenants = len(errors)

    if failed_tenants > 0:
        logger.warning(
            f"Audit log retention purge completed with errors: "
            f"{successful_tenants} tenants processed, {failed_tenants} failed, "
            f"{total_purged} total logs purged",
            extra={
                "total_tenants": total_tenants,
                "successful_tenants": successful_tenants,
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
                "successful_tenants": successful_tenants,
                "total_purged": total_purged,
                "purge_stats": purge_stats,
            },
        )

    return {
        "purge_stats": purge_stats,
        "errors": errors,
        "total_tenants": total_tenants,
        "successful_tenants": successful_tenants,
        "total_purged": total_purged,
        "success": len(errors) == 0,
    }


@worker.cron_job(hour=4, minute=0)  # Daily at 04:00 UTC
async def purge_old_conversations(container: Container):
    """
    Daily cron job to purge old conversation data based on retention policies.

    Runs at 04:00 UTC (5:00 AM Swedish winter, 6:00 AM summer) to minimize user impact.
    Scheduled 2 hours after audit log purge to ensure no overlap (audit purge may take 1-2 hours).

    Deletes:
    - Old questions (based on assistant/space/tenant retention hierarchy)
    - Old app runs (based on app/space/tenant retention hierarchy)
    - Orphaned sessions (sessions with no questions, older than cleanup threshold)

    Uses hierarchical retention policy resolution:
    1. Entity-level (Assistant/App) - highest priority
    2. Space-level
    3. Tenant-level (if enabled)
    4. NULL = keep forever (default)

    Returns:
        Dictionary with deletion statistics
    """
    from intric.data_retention.infrastructure.data_retention_service import (
        DataRetentionService,
    )
    from intric.main.logging import get_logger

    logger = get_logger(__name__)

    logger.info("Starting conversation data retention purge")

    session = container.session()
    retention_service = DataRetentionService(session)

    # Delete old questions based on hierarchical retention policies
    questions_deleted = await retention_service.delete_old_questions()

    # Delete old app runs based on hierarchical retention policies
    app_runs_deleted = await retention_service.delete_old_app_runs()

    # Delete orphaned sessions (no questions, past cleanup threshold)
    sessions_deleted = await retention_service.delete_old_sessions()

    total_deleted = questions_deleted + app_runs_deleted + sessions_deleted

    logger.info(
        "Conversation data retention purge completed",
        extra={
            "questions_deleted": questions_deleted,
            "app_runs_deleted": app_runs_deleted,
            "sessions_deleted": sessions_deleted,
            "total_deleted": total_deleted,
        },
    )

    return {
        "questions_deleted": questions_deleted,
        "app_runs_deleted": app_runs_deleted,
        "sessions_deleted": sessions_deleted,
        "total_deleted": total_deleted,
        "success": True,
    }
