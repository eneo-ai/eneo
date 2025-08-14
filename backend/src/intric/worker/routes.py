from intric.jobs.task_models import Transcription, UploadInfoBlob
from intric.main.container.container import Container
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.website import UpdateInterval
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


# Daily crawl at 2 AM
@worker.cron_job(hour=2, minute=0)
async def crawl_daily_websites(container: Container):
    return await queue_website_crawls(container=container, interval=UpdateInterval.DAILY)


# Every 3 days crawl at 2 AM (on days 1, 4, 7, 10, 13, 16, 19, 22, 25, 28)
@worker.cron_job(day=(1, 4, 7, 10, 13, 16, 19, 22, 25, 28), hour=2, minute=0)
async def crawl_every_3_days_websites(container: Container):
    return await queue_website_crawls(container=container, interval=UpdateInterval.EVERY_3_DAYS)


# Weekly crawl on Friday at 11 PM (keeping original time for backward compatibility)
@worker.cron_job(weekday="fri", hour=23, minute=0)
async def crawl_weekly_websites(container: Container):
    return await queue_website_crawls(container=container, interval=UpdateInterval.WEEKLY)


# Every 2 weeks crawl on Friday at 11 PM (on days 1-7 and 15-21)
@worker.cron_job(weekday="fri", day=(1, 2, 3, 4, 5, 6, 7, 15, 16, 17, 18, 19, 20, 21), hour=23, minute=0)
async def crawl_every_2_weeks_websites(container: Container):
    return await queue_website_crawls(container=container, interval=UpdateInterval.EVERY_2_WEEKS)


# Monthly crawl on the 1st at 2 AM
@worker.cron_job(day=1, hour=2, minute=0)
async def crawl_monthly_websites(container: Container):
    return await queue_website_crawls(container=container, interval=UpdateInterval.MONTHLY)
