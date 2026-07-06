"""Result models for crawl execution.

CrawledPage is the wire/spool shape of one extracted page; Crawl is what the
crawler's ``crawl(...)`` context manager yields to the worker. These are the
stable contract the worker consumes, independent of who executes the crawl.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str
    # HTTP cache validators from the fetch; persisted so the next crawl can
    # send them as conditional-GET hints
    etag: Optional[str] = None
    last_modified: Optional[str] = None


@dataclass
class Crawl:
    """Result of a web crawl operation.

    Attributes:
        pages: Iterator of crawled pages
        files: Optional iterator of downloaded files
        is_partial: True if crawl was terminated early (timeout, etc.)
        termination_reason: Why crawl ended ("completed", "timeout", "error")
        pages_count: Number of pages collected (for partial results reporting)
        unchanged_urls: URLs the server answered 304 for (body never sent);
            their stored content and embeddings are still current
    """

    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]
    is_partial: bool = False
    termination_reason: str = "completed"
    pages_count: int = 0
    unchanged_urls: list[str] = field(default_factory=list[str])
