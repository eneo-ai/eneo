from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Final
from uuid import UUID

from intric.embedding_models.domain.embedding_batch import EmbeddingUsageSource
from intric.websites.domain.website import UpdateInterval

SCHEDULE_FREQUENCY_WEIGHTS: Final[dict[UpdateInterval, float]] = {
    UpdateInterval.DAILY: 7.0,
    UpdateInterval.EVERY_OTHER_DAY: 3.5,
    UpdateInterval.WEEKLY: 1.0,
    UpdateInterval.NEVER: 0.0,
}

# Operator threshold below which a row's retention rate is flagged
# wasteful (the hash gate / source-skip did not retain enough content).
# Mirrors the frontend constant in crawlerWebsiteProcessing.ts so the
# server-side filter ("Endast låg behållning") matches the row badge.
LOW_RETENTION_THRESHOLD: Final[float] = 0.5

# Minimum indexed content for the source-skip-drift flag to fire.
# Below this floor the signal is noise (a website with 1 page can't
# meaningfully demonstrate sitemap drift). Mirrors the frontend
# constant so server-filtered rows and badge-flagged rows match.
SOURCE_SKIP_DRIFT_MIN_INDEXED: Final[int] = 50


class CrawlerWebsiteProcessingSort(str, Enum):
    LOAD_PRESSURE = "load_pressure"
    FAILURES = "failures"
    INDEXED_SIZE = "indexed_size"
    LOW_RETENTION = "low_retention"
    RUNS = "runs"
    TOKENS = "tokens"
    RECENT = "recent"


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
    website_url: str
    tenant_id: UUID
    tenant_display_name: str | None
    space_id: UUID | None
    space_name: str | None
    collection_id: UUID | None
    collection_name: str | None
    owner_user_id: UUID | None
    owner_email: str | None
    update_interval: UpdateInterval | None
    indexed_size_bytes: int
    latest_run_at: datetime | None
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
    embedding_input_tokens: int | None
    embedding_total_cost_usd: Decimal | None
    latest_embedding_model_name_snapshot: str | None
    latest_embedding_model_litellm_name_snapshot: str | None
    latest_embedding_model_provider_snapshot: str | None
    latest_embedding_input_tokens: int | None
    latest_embedding_total_cost_usd: Decimal | None
    latest_embedding_usage_source: EmbeddingUsageSource | None


@dataclass(frozen=True, slots=True)
class CrawlerWebsiteProcessingAggregateSummary:
    website_count: int
    total_runs: int
    terminal_runs: int
    failed_runs: int
    pages_crawled: int
    files_downloaded: int
    retained_content_count: int
    files_too_large_skipped: int
    failed_item_count: int
    indexed_size_bytes: int
    embedding_input_tokens: int | None
    embedding_total_cost_usd: Decimal | None
    action_required_count: int


@dataclass(frozen=True, slots=True)
class CrawlerWebsiteProcessingSpaceRollupItem:
    space_id: UUID | None
    space_name: str | None
    website_count: int
    total_runs: int
    pages_crawled: int
    files_downloaded: int
    indexed_size_bytes: int
    embedding_input_tokens: int | None
    embedding_total_cost_usd: Decimal | None
    action_required_count: int
    latest_run_at: datetime | None


@dataclass(frozen=True, slots=True)
class CrawlerWebsiteProcessingAggregate:
    items: tuple[CrawlerWebsiteProcessingAggregateItem, ...]
    summary: CrawlerWebsiteProcessingAggregateSummary
    space_rollup: tuple[CrawlerWebsiteProcessingSpaceRollupItem, ...]
    total: int
    limit: int
    offset: int
    days: int
    since: datetime
    until: datetime
    tenant_id: UUID | None
