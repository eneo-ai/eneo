from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CrawlerWebsiteProcessingAggregateItem:
    website_id: UUID
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    total_runs: int
    terminal_runs: int
    failed_runs: int
    pages_crawled: int
    files_downloaded: int
    pages_hash_retained: int
    files_hash_retained: int
    pages_source_retained: int
    files_too_large_skipped: int
    pages_failed: int
    files_failed: int


@dataclass(frozen=True, slots=True)
class CrawlerWebsiteProcessingAggregate:
    items: tuple[CrawlerWebsiteProcessingAggregateItem, ...]
    total: int
    limit: int
    offset: int
    days: int
    since: datetime
    until: datetime
    tenant_id: UUID | None
