from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from intric.main.models import Status


class CrawlAbortConflictCode(StrEnum):
    RUNNING_ABORT_NOT_IMPLEMENTED = "RUNNING_ABORT_NOT_IMPLEMENTED"
    CRAWL_NOT_ABORTABLE = "CRAWL_NOT_ABORTABLE"


def is_queued_crawl_abortable_status(status: Status) -> bool:
    """Return statuses currently accepted by the queued-abort path."""
    return status == Status.QUEUED


def is_queued_crawl_abortable_target(*, status: Status, has_crawl_run: bool) -> bool:
    """Return whether a queued job can be addressed by the CrawlRun-backed abort path."""
    return has_crawl_run and is_queued_crawl_abortable_status(status)


@dataclass(frozen=True, slots=True)
class CrawlAbortWebsite:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CrawlAbortSucceeded:
    job_id: UUID
    crawl_run_id: UUID
    website: CrawlAbortWebsite
    already_terminal: bool


@dataclass(frozen=True, slots=True)
class CrawlAbortNotFound:
    job_id: UUID


@dataclass(frozen=True, slots=True)
class CrawlAbortConflict:
    job_id: UUID
    code: CrawlAbortConflictCode


CrawlAbortResult: TypeAlias = (
    CrawlAbortSucceeded | CrawlAbortNotFound | CrawlAbortConflict
)
