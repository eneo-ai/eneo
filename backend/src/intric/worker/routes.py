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


# Daily crawl at 2 AM Sweden time
# Runs every day to crawl websites with 'daily' update interval
@worker.cron_job(hour=2, minute=0)
async def crawl_daily_websites(container: Container):
    """Queue crawl tasks for all websites configured for daily updates.

    This cron job triggers daily at 2 AM Sweden time and processes all websites
    that have their update_interval set to 'daily'. Each website gets its own
    crawl task queued in the background worker system.
    """
    return await queue_website_crawls(container=container, interval=UpdateInterval.DAILY)


# Every other day crawl at 2 AM Sweden time (alternating days)
# Runs on odd days of the month to provide every-other-day functionality
@worker.cron_job(day=(1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31), hour=2, minute=0)
async def crawl_every_other_day_websites(container: Container):
    """Queue crawl tasks for all websites configured for every-other-day updates.

    This cron job triggers every other day at 2 AM Sweden time on odd-numbered
    days of the month. This provides a middle ground between daily and weekly crawls.
    """
    return await queue_website_crawls(container=container, interval=UpdateInterval.EVERY_OTHER_DAY)


# Weekly crawl on Friday at 11 PM Sweden time
# Runs weekly to crawl websites with 'weekly' update interval
@worker.cron_job(weekday="fri", hour=23, minute=0)
async def crawl_weekly_websites(container: Container):
    """Queue crawl tasks for all websites configured for weekly updates.

    This cron job triggers every Friday at 11 PM Sweden time and processes all
    websites that have their update_interval set to 'weekly'. The Friday evening
    timing ensures minimal impact on business hours.
    """
    return await queue_website_crawls(container=container, interval=UpdateInterval.WEEKLY)
