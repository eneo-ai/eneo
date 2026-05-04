from intric.jobs.job_manager import job_manager
from intric.jobs.job_models import Task


class SysAdminService:
    async def run_crawl_on_weekly_websites(self):
        return await job_manager.enqueue_jobless(Task.CRAWL_ALL_WEBSITES)
