"""Result models for crawl execution.

CrawledPage is the wire/spool shape of one extracted page; Crawl is what the
crawler's ``crawl(...)`` context manager yields to the worker. These are the
stable contract the worker consumes, independent of who executes the crawl.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str


@dataclass
class Crawl:
    """Result of a web crawl operation.

    Attributes:
        pages: Iterator of crawled pages
        files: Optional iterator of downloaded files
        is_partial: True if crawl was terminated early (timeout, etc.)
        termination_reason: Why crawl ended ("completed", "timeout", "error")
        pages_count: Number of pages collected (for partial results reporting)
    """

    pages: Iterable[CrawledPage]
    files: Optional[Iterable[Path]]
    is_partial: bool = False
    termination_reason: str = "completed"
    pages_count: int = 0
