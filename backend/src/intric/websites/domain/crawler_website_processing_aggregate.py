from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from intric.websites.domain.website import UpdateInterval

SCHEDULE_FREQUENCY_WEIGHTS: Final[dict[UpdateInterval, float]] = {
    UpdateInterval.DAILY: 7.0,
    UpdateInterval.EVERY_OTHER_DAY: 3.5,
    UpdateInterval.WEEKLY: 1.0,
    UpdateInterval.NEVER: 0.0,
}


def parse_update_interval_for_cost_score(value: object) -> UpdateInterval | None:
    if value is None:
        return None
    try:
        return UpdateInterval(str(value))
    except ValueError:
        return None


def schedule_frequency_weight(update_interval: UpdateInterval | None) -> float:
    if update_interval is None:
        return 0.0
    return SCHEDULE_FREQUENCY_WEIGHTS[update_interval]


def retention_rate(*, retained_count: int, indexed_content_count: int) -> float:
    if indexed_content_count <= 0:
        return 0.0
    return retained_count / indexed_content_count


def cost_pressure_score(
    *,
    schedule_weight: float,
    indexed_content_count: int,
    retained_count: int,
) -> float:
    if indexed_content_count <= 0:
        return 0.0
    return (
        schedule_weight
        * indexed_content_count
        * (
            1.0
            - retention_rate(
                retained_count=retained_count,
                indexed_content_count=indexed_content_count,
            )
        )
    )


@dataclass(frozen=True, slots=True)
class CrawlerWebsiteProcessingAggregateItem:
    website_id: UUID
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    update_interval: UpdateInterval | None
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
    schedule_frequency_weight: float
    indexed_content_count: int
    retention_rate: float
    cost_pressure_score: float


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
