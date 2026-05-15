from dataclasses import dataclass
from uuid import UUID

from intric.websites.domain.website import UpdateInterval


@dataclass(frozen=True, slots=True)
class CrawlerScheduledIntervalBucket:
    """Aggregates `Websites.size`, maintained from persisted info-blob byte sizes."""

    update_interval: UpdateInterval
    website_count: int
    total_size_bytes: int


@dataclass(frozen=True, slots=True)
class CrawlerScheduledAggregate:
    """Aggregates `Websites.size`, maintained from persisted info-blob byte sizes."""

    buckets: tuple[CrawlerScheduledIntervalBucket, ...]
    total_websites: int
    total_size_bytes: int
    unparseable_update_interval_website_count: int
    unparseable_update_interval_total_size_bytes: int
    tenant_id: UUID | None
