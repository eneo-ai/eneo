from typing import TYPE_CHECKING

from intric.websites.domain.crawl_run import CrawlRun

if TYPE_CHECKING:
    from intric.jobs.task_service import TaskService
    from intric.websites.domain.crawl_run_repo import CrawlRunRepository
    from intric.websites.domain.website import Website


class CrawlService:
    def __init__(self, repo: "CrawlRunRepository", task_service: "TaskService"):
        self.repo = repo
        self.task_service = task_service

    async def crawl(self, website: "Website"):
        crawl_run = CrawlRun.create(website=website)
        crawl_run = await self.repo.add(crawl_run=crawl_run)

        crawl_job = await self.task_service.queue_crawl(
            name=website.name,
            run_id=crawl_run.id,
            website_id=website.id,
            url=website.url,
            download_files=website.download_files,
            crawl_type=website.crawl_type,
            http_user=website.auth_username if website.requires_auth else None,
            http_pass=website.auth_password if website.requires_auth else None,
        )

        crawl_run.update(job_id=crawl_job.id)

        crawl_run = await self.repo.update(crawl_run=crawl_run)

        return crawl_run
