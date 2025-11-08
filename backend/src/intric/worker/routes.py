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

    For each tenant:
    - Retrieves retention policy (default: 365 days)
    - Soft-deletes logs older than retention period
    - Updates purge statistics

    Returns:
        Dictionary with purge statistics per tenant
    """
    from intric.audit.application.retention_service import RetentionService
    from intric.main.logging import get_logger

    logger = get_logger(__name__)
    session = container.session()

    retention_service = RetentionService(session)
    purge_stats = await retention_service.purge_all_tenants()

    total_purged = sum(stats["purged_count"] for stats in purge_stats.values())

    logger.info(
        "Audit log retention purge completed",
        extra={
            "total_tenants": len(purge_stats),
            "total_purged": total_purged,
            "purge_stats": purge_stats,
        },
    )

    return purge_stats
