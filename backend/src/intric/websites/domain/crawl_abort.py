from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

from intric.main.models import Status


class CrawlAbortConflictCode(StrEnum):
    CRAWL_NOT_ABORTABLE = "CRAWL_NOT_ABORTABLE"


_ABORTABLE_STATUSES: frozenset[Status] = frozenset({Status.QUEUED, Status.IN_PROGRESS})


def is_crawl_abortable_status(status: Status) -> bool:
    """Return statuses currently accepted by the tenant-admin abort path.

    QUEUED and IN_PROGRESS share the same canonical abort flow: commit a
    terminal CRAWL_ABORTED event so the worker's heartbeat preemption check
    observes FAILED and exits without running unsafe stale cleanup. Terminal
    statuses are filtered separately so already-aborted jobs are idempotent.
    """
    return status in _ABORTABLE_STATUSES


def is_crawl_abortable_target(*, status: Status, has_crawl_run: bool) -> bool:
    """Return whether the job can be addressed by the CrawlRun-backed abort path.

    A `CrawlRun` row is required because the abort flow writes a terminal
    outcome on it; orphan jobs without a run cannot be aborted by this path.
    """
    return has_crawl_run and is_crawl_abortable_status(status)


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
