from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID


class CrawlAbortConflictCode(StrEnum):
    RUNNING_ABORT_NOT_IMPLEMENTED = "RUNNING_ABORT_NOT_IMPLEMENTED"
    CRAWL_NOT_ABORTABLE = "CRAWL_NOT_ABORTABLE"


@dataclass(frozen=True, slots=True)
class CrawlAbortSucceeded:
    job_id: UUID
    crawl_run_id: UUID
    website_id: UUID
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
