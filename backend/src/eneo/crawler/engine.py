"""Backend-neutral contract for crawl execution.

Durable crawl state belongs to Eneo's website and crawl-run models. Engines only
execute one bounded request and emit facts as they become available. Keeping the
contract event-based lets the worker persist pages incrementally instead of
requiring every engine to build a complete spool before ingestion starts.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from eneo.websites.domain.crawl_run import CrawlType


@dataclass(frozen=True, slots=True)
class CrawlLimits:
    max_pages: int
    max_seconds: float
    request_timeout_seconds: float
    max_response_bytes: int
    max_file_bytes: int = 10 * 1024 * 1024
    dns_timeout_seconds: float = 30.0
    concurrency: int = 4
    request_delay_seconds: float = 0.0
    retries: int = 2

    def __post_init__(self) -> None:
        positive = {
            "max_pages": self.max_pages,
            "max_seconds": self.max_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "max_response_bytes": self.max_response_bytes,
            "max_file_bytes": self.max_file_bytes,
            "dns_timeout_seconds": self.dns_timeout_seconds,
            "concurrency": self.concurrency,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.request_delay_seconds < 0:
            raise ValueError("request_delay_seconds cannot be negative")
        if self.retries < 0:
            raise ValueError("retries cannot be negative")


@dataclass(frozen=True, slots=True)
class CrawlRequest:
    url: str
    crawl_type: CrawlType
    download_files: bool
    obey_robots: bool
    limits: CrawlLimits
    http_user: str | None = None
    http_pass: str | None = field(default=None, repr=False)
    conditional_gets: tuple["ConditionalGet", ...] = ()


@dataclass(frozen=True, slots=True)
class ConditionalGet:
    url: str
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class PageCrawled:
    url: str
    title: str
    content: str
    etag: str | None
    last_modified: str | None
    file_links: tuple[str, ...] = ()
    type: Literal["page"] = "page"


@dataclass(frozen=True, slots=True)
class PageFailed:
    url: str
    reason: str
    status_code: int | None = None
    retryable: bool = False
    type: Literal["failed"] = "failed"


@dataclass(frozen=True, slots=True)
class PageUnchanged:
    url: str
    type: Literal["unchanged"] = "unchanged"


@dataclass(frozen=True, slots=True)
class FileDownloaded:
    url: str
    filename: str
    path: Path
    type: Literal["file"] = "file"


@dataclass(frozen=True, slots=True)
class FileFailed:
    url: str
    reason: str
    status_code: int | None = None
    retryable: bool = False
    type: Literal["file_failed"] = "file_failed"


@dataclass(frozen=True, slots=True)
class CrawlFinished:
    status: Literal["completed", "partial"]
    pages_crawled: int
    pages_failed: int
    pages_unchanged: int = 0
    files_downloaded: int = 0
    files_failed: int = 0
    sitemap_fingerprint: str | None = None
    sitemap_entries: int = 0
    reason: str | None = None
    type: Literal["done"] = "done"


CrawlEvent = (
    PageCrawled
    | PageFailed
    | PageUnchanged
    | FileDownloaded
    | FileFailed
    | CrawlFinished
)


class CrawlEngine(Protocol):
    """Execution-only crawler interface implemented by every backend."""

    def crawl(self, request: CrawlRequest) -> AsyncIterator[CrawlEvent]: ...
