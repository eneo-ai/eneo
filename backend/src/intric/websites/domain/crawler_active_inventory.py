from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from intric.main.models import Status
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
from intric.websites.domain.website import UpdateInterval


@dataclass(frozen=True, slots=True)
class CrawlerActiveInventoryItem:
    """Active crawl job row; missing crawl-run fields mean an orphan queued job.

    Attribution fields (space/collection/user) come from LEFT JOINs and are
    nullable to keep visibility intact for legacy websites without a Space
    or Collection. The user-started-by attribution is the `Jobs.user_id`
    creator, which can differ from the website creator if a teammate
    triggered the crawl.
    """

    job_id: UUID
    crawl_run_id: UUID | None
    website_id: UUID | None
    website_name: str | None
    space_id: UUID | None
    space_name: str | None
    collection_id: UUID | None
    collection_name: str | None
    user_started_by_id: UUID | None
    user_started_by_email: str | None
    # Update interval for the website, nullable for orphan jobs where
    # the Websites LEFT JOIN returned no row. Surfaces so the admin
    # active-inventory row can offer a per-row "Change schedule"
    # affordance without round-tripping through the failure-inventory
    # tab.
    update_interval: UpdateInterval | None
    tenant_id: UUID | None
    tenant_display_name: str | None
    status: Status
    lifecycle_state: CrawlLifecycle
    is_abortable: bool
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
