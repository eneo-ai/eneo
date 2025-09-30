from intric.jobs.task_models import Transcription, UploadInfoBlob
from intric.main.container.container import Container
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.worker.crawl_tasks import crawl_task, queue_website_crawls
from intric.worker.upload_tasks import transcription_task, upload_info_blob_task
from intric.worker.worker import Worker

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


@worker.cron_job(hour=1, minute=0)  # Daily at 1:00 UTC (3:00 AM Swedish time)
async def crawl_all_websites(container: Container):
    """Daily cron job to process websites based on their update intervals.

    Why: Single daily cron is simpler to maintain than multiple schedules.
    Runs at 3 AM Swedish time to minimize user impact.
    Engine-agnostic - works for both Scrapy and Crawl4AI through existing abstraction.

    Schedule handles:
    - DAILY: Every day
    - EVERY_OTHER_DAY: Every 2 days based on last crawl
    - WEEKLY: Fridays (preserving existing behavior)
    - NEVER: Skipped
    """
    return await queue_website_crawls(container=container)
