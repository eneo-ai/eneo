from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCategory,
    CrawlOutcomeCode,
)


class CrawlerFailureClusterSource(str, Enum):
    ALL = "all"
    WATCHDOG_ONLY = "watchdog_only"


@dataclass(frozen=True, slots=True)
class CrawlerFailureClusterItem:
    website_id: UUID
    website_url: str
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    space_id: UUID | None
    space_name: str | None
    owner_user_id: UUID | None
    owner_email: str | None
    outcome_code: CrawlOutcomeCode
    outcome_category: CrawlOutcomeCategory
    occurrences: int
    watchdog_occurrences: int
    first_failed_at: datetime
    latest_failed_at: datetime
    sample_crawl_run_id: UUID
    pages_crawled: int
    files_downloaded: int
    pages_failed: int
    files_failed: int


@dataclass(frozen=True, slots=True)
class CrawlerFailureClusters:
    items: tuple[CrawlerFailureClusterItem, ...]
    total: int
    limit: int
    offset: int
    days: int
    since: datetime
    until: datetime
    source: CrawlerFailureClusterSource
    outcome_category: CrawlOutcomeCategory | None
