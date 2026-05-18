from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from intric.jobs.job_manager import JobRuntimeStatus, job_manager


class CrawlJobStatus(StrEnum):
    DEFERRED = "deferred"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class CrawlJobStatusKnown:
    job_id: UUID
    status: CrawlJobStatus


@dataclass(frozen=True, slots=True)
class CrawlJobStatusLookupFailed:
    job_id: UUID
    error: Exception


CrawlJobStatusResult: TypeAlias = CrawlJobStatusKnown | CrawlJobStatusLookupFailed

_RUNTIME_TO_CRAWL_STATUS: dict[JobRuntimeStatus, CrawlJobStatus] = {
    JobRuntimeStatus.DEFERRED: CrawlJobStatus.DEFERRED,
    JobRuntimeStatus.QUEUED: CrawlJobStatus.QUEUED,
    JobRuntimeStatus.IN_PROGRESS: CrawlJobStatus.IN_PROGRESS,
    JobRuntimeStatus.COMPLETE: CrawlJobStatus.COMPLETE,
    JobRuntimeStatus.NOT_FOUND: CrawlJobStatus.NOT_FOUND,
}


def _to_crawl_job_status(status: JobRuntimeStatus) -> CrawlJobStatus:
    return _RUNTIME_TO_CRAWL_STATUS[status]


async def get_crawl_job_status(job_id: UUID) -> CrawlJobStatusResult:
    try:
        status = await job_manager.get_job_status(job_id)
        crawl_status = _to_crawl_job_status(status)
    except Exception as exc:
        return CrawlJobStatusLookupFailed(job_id=job_id, error=exc)

    return CrawlJobStatusKnown(
        job_id=job_id,
        status=crawl_status,
    )
