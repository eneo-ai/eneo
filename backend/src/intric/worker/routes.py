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

worker = Worker()


@worker.function()
async def upload_info_blob(job_id: str, params: UploadInfoBlob, container: Container):
    return await upload_info_blob_task(job_id=job_id, params=params, container=container)


@worker.function()
async def transcription(job_id: str, params: Transcription, container: Container):
    return await transcription_task(job_id=job_id, params=params, container=container)


@worker.function()
async def crawl(job_id: str, params: CrawlTask, container: Container):
    return await crawl_task(job_id=job_id, params=params, container=container)


@worker.cron_job(weekday="fri", hour=23, minute=0)
async def crawl_all_websites(container: Container):
    return await queue_website_crawls(container=container)


@worker.function()
async def update_model_usage_stats(job_id: str, params: dict, container: Container):
    """Worker function for updating model usage statistics.
    
    Note: params is a dict here because it comes from ARQ, but we validate it
    by creating UpdateUsageStatsTaskParams inside the task function.
    """
    return await update_model_usage_stats_task(job_id=job_id, params=params, container=container)

@worker.function()
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
    
    return await recalculate_tenant_usage_stats(container=container, tenant_id=tenant_id)


@worker.cron_job(hour=19, minute=00)  # Daily at 02:00 UTC
async def recalculate_usage_stats(container: Container):
    """Nightly recalculation of all tenant usage statistics"""
    return await recalculate_all_tenants_usage_stats(container=container)
