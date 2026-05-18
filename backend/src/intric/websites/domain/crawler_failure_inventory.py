from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.website import UpdateInterval


class CrawlerFailureState(str, Enum):
    AUTO_DISABLED = "AUTO_DISABLED"
    BACKED_OFF = "BACKED_OFF"


@dataclass(frozen=True, slots=True)
class CrawlerFailureInventoryItem:
    website_id: UUID
    website_url: str
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    space_id: UUID | None
    space_name: str | None
    owner_user_id: UUID | None
    owner_email: str | None
    state: CrawlerFailureState
    update_interval: UpdateInterval
    consecutive_failures: int
    next_retry_at: datetime | None
    last_crawled_at: datetime | None
    updated_at: datetime
    latest_failure_outcome_code: CrawlOutcomeCode | None
    latest_failure_at: datetime | None


@dataclass(frozen=True, slots=True)
class CrawlerFailureInventory:
    items: tuple[CrawlerFailureInventoryItem, ...]
    total: int
    limit: int
    offset: int
