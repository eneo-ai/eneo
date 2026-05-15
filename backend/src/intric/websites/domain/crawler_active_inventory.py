from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from intric.main.models import Status
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle


@dataclass(frozen=True, slots=True)
class CrawlerActiveInventoryItem:
    """Active crawl job row; missing crawl-run fields mean an orphan queued job."""

    job_id: UUID
    crawl_run_id: UUID | None
    website_id: UUID | None
    tenant_id: UUID | None
    status: Status
    lifecycle_state: CrawlLifecycle
    job_created_at: datetime
    job_updated_at: datetime
    crawl_run_created_at: datetime | None
    pages_crawled: int | None
    files_downloaded: int | None
    pages_failed: int | None
    files_failed: int | None
    pages_source_retained: int | None
    pages_hash_retained: int | None
    files_hash_retained: int | None
    files_too_large_skipped: int | None


@dataclass(frozen=True, slots=True)
class CrawlerActiveInventory:
    items: tuple[CrawlerActiveInventoryItem, ...]
    total: int
    limit: int
    offset: int
