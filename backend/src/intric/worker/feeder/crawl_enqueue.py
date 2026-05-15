from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from intric.jobs.job_manager import job_manager
from intric.jobs.job_models import Task
from intric.websites.crawl_dependencies.crawl_models import CrawlTask
from intric.websites.domain.crawl_run import CrawlType


@dataclass(frozen=True, slots=True)
class CrawlEnqueued:
    job_id: UUID


@dataclass(frozen=True, slots=True)
class CrawlEnqueueDuplicate:
    job_id: UUID


@dataclass(frozen=True, slots=True)
class CrawlEnqueueFailed:
    job_id: UUID
    error: Exception


CrawlEnqueueResult: TypeAlias = (
    CrawlEnqueued | CrawlEnqueueDuplicate | CrawlEnqueueFailed
)


async def enqueue_crawl_job(
    *,
    job_id: UUID,
    user_id: UUID,
    website_id: UUID,
    run_id: UUID,
    url: str,
    download_files: bool,
    crawl_type: CrawlType,
) -> CrawlEnqueueResult:
    """Enqueue an already-created crawl job to ARQ.

    Duplicate means `job_manager.enqueue(...)` returned false. Exception text is
    never parsed as a duplicate signal.
    """
    params = CrawlTask(
        user_id=user_id,
        website_id=website_id,
        run_id=run_id,
        url=url,
        download_files=download_files,
        crawl_type=crawl_type,
    )

    try:
        enqueued = await job_manager.enqueue(
            task=Task.CRAWL,
            job_id=job_id,
            params=params,
        )
    except Exception as exc:
        return CrawlEnqueueFailed(
            job_id=job_id,
            error=exc,
        )

    if enqueued:
        return CrawlEnqueued(job_id=job_id)
    return CrawlEnqueueDuplicate(job_id=job_id)
