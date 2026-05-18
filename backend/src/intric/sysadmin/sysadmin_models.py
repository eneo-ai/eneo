from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from intric.main.models import ModelId
from intric.spaces.api.space_models import AddSpaceMemberRequest
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawler_baseline import (
    CrawlerBaselineMetrics as DomainCrawlerBaselineMetrics,
)
from intric.websites.domain.crawler_baseline import (
    CrawlerBaselineProcessingTotals as DomainCrawlerBaselineProcessingTotals,
)
from intric.websites.domain.crawler_baseline import (
    CrawlOutcomeBucket as DomainCrawlOutcomeBucket,
)
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventory as DomainCrawlerFailureInventory,
)
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventoryItem as DomainCrawlerFailureInventoryItem,
)
from intric.websites.domain.crawler_failure_inventory import CrawlerFailureState
from intric.websites.domain.crawler_recent_failures import (
    CrawlerRecentFailures as DomainCrawlerRecentFailures,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    CrawlerWebsiteProcessingAggregate as DomainCrawlerWebsiteProcessingAggregate,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    CrawlerWebsiteProcessingAggregateItem as DomainCrawlerWebsiteProcessingAggregateItem,
)
from intric.websites.domain.website import UpdateInterval
from intric.websites.presentation.crawler_admin_models import (
    CrawlerRecentFailuresResponse,
)
from intric.worker.redis.client import (
    WatchdogLifecycleSnapshot as DomainWatchdogLifecycleSnapshot,
)
from intric.worker.redis.client import (
    WatchdogMetricsSnapshot as DomainWatchdogMetricsSnapshot,
)
from intric.worker.redis.client import (
    WatchdogStatusSnapshot as DomainWatchdogStatusSnapshot,
)


def _empty_model_id_list() -> list[ModelId]:
    return []


def _empty_member_list() -> list[AddSpaceMemberRequest]:
    return []


class InfoBlobDifference(BaseModel):
    database_ids: set[str]
    datastore_ids: set[str]
    database_difference: set[str]
    datastore_difference: set[str]


class ExtraBlobs(BaseModel):
    count: int
    ids: list[str]


class AggregatedExtraBlobs(BaseModel):
    database: ExtraBlobs
    datastore: ExtraBlobs


class InfoBlobDifferencePublic(BaseModel):
    database_count: int
    datastore_count: int
    extra_info_blobs: AggregatedExtraBlobs


class CreateAndImportSpaceRequest(BaseModel):
    name: str
    embedding_model: ModelId
    assistants: list[ModelId] = Field(default_factory=_empty_model_id_list)
    groups: list[ModelId] = Field(default_factory=_empty_model_id_list)
    websites: list[ModelId] = Field(default_factory=_empty_model_id_list)
    members: list[AddSpaceMemberRequest] = Field(default_factory=_empty_member_list)


class CrawlOutcomeBucket(BaseModel):
    code: CrawlOutcomeCode
    count: int = Field(
        ge=0,
        description="Terminal crawl runs with this strict typed outcome code.",
    )

    @classmethod
    def from_domain(cls, bucket: DomainCrawlOutcomeBucket) -> "CrawlOutcomeBucket":
        return cls(code=bucket.code, count=bucket.count)


class CrawlerBaselineProcessingTotals(BaseModel):
    pages_crawled: int = Field(ge=0)
    files_downloaded: int = Field(ge=0)
    pages_hash_retained: int = Field(ge=0)
    files_hash_retained: int = Field(ge=0)
    pages_source_retained: int = Field(ge=0)
    files_too_large_skipped: int = Field(ge=0)
    pages_failed: int = Field(ge=0)
    files_failed: int = Field(ge=0)
    embedding_input_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Provider-reported embedding input tokens indexed in the window.",
    )
    embedding_total_cost_usd: str | None = Field(
        default=None,
        description="Run-time USD cost snapshot for provider-reported embedding usage.",
    )

    @classmethod
    def from_domain(
        cls, totals: DomainCrawlerBaselineProcessingTotals
    ) -> "CrawlerBaselineProcessingTotals":
        return cls(
            pages_crawled=totals.pages_crawled,
            files_downloaded=totals.files_downloaded,
            pages_hash_retained=totals.pages_hash_retained,
            files_hash_retained=totals.files_hash_retained,
            pages_source_retained=totals.pages_source_retained,
            files_too_large_skipped=totals.files_too_large_skipped,
            pages_failed=totals.pages_failed,
            files_failed=totals.files_failed,
            embedding_input_tokens=totals.embedding_input_tokens,
            embedding_total_cost_usd=(
                str(totals.embedding_total_cost_usd)
                if totals.embedding_total_cost_usd is not None
                else None
            ),
        )


class CrawlerBaselineResponse(BaseModel):
    window_days: int = Field(ge=1, le=30)
    since: datetime
    until: datetime
    tenant_id: UUID | None
    total_runs: int = Field(ge=0)
    terminal_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    failed_runs_without_typed_outcome: int = Field(ge=0)
    typed_failed_runs: int = Field(ge=0)
    typed_unknown_failed_runs: int = Field(ge=0)
    typed_unknown_failed_rate_percent: float = Field(ge=0)
    legacy_null_outcome_runs: int = Field(
        ge=0,
        description="Terminal crawl runs that still have no typed outcome code.",
    )
    unparseable_outcome_runs: int = Field(
        ge=0,
        description=(
            "Terminal crawl runs with an outcome code that is not in the current "
            "closed enum."
        ),
    )
    outcome_counts: list[CrawlOutcomeBucket] = Field(
        description="Terminal crawl runs grouped by strict typed outcome code."
    )
    processing_totals: CrawlerBaselineProcessingTotals

    @classmethod
    def from_domain(
        cls, metrics: DomainCrawlerBaselineMetrics
    ) -> "CrawlerBaselineResponse":
        return cls(
            window_days=metrics.window_days,
            since=metrics.since,
            until=metrics.until,
            tenant_id=metrics.tenant_id,
            total_runs=metrics.total_runs,
            terminal_runs=metrics.terminal_runs,
            failed_runs=metrics.failed_runs,
            failed_runs_without_typed_outcome=(
                metrics.failed_runs_without_typed_outcome
            ),
            typed_failed_runs=metrics.typed_failed_runs,
            typed_unknown_failed_runs=metrics.typed_unknown_failed_runs,
            typed_unknown_failed_rate_percent=(
                metrics.typed_unknown_failed_rate_percent
            ),
            legacy_null_outcome_runs=metrics.legacy_null_outcome_runs,
            unparseable_outcome_runs=metrics.unparseable_outcome_runs,
            outcome_counts=[
                CrawlOutcomeBucket.from_domain(bucket)
                for bucket in metrics.outcome_counts
            ],
            processing_totals=CrawlerBaselineProcessingTotals.from_domain(
                metrics.processing_totals
            ),
        )


class CrawlerFailureInventoryItem(BaseModel):
    website_id: UUID
    website_url: str
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    state: CrawlerFailureState
    update_interval: UpdateInterval
    consecutive_failures: int = Field(ge=0)
    next_retry_at: datetime | None
    last_crawled_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerFailureInventoryItem
    ) -> "CrawlerFailureInventoryItem":
        return cls(
            website_id=item.website_id,
            website_url=item.website_url,
            website_name=item.website_name,
            tenant_id=item.tenant_id,
            tenant_display_name=item.tenant_display_name,
            state=item.state,
            update_interval=item.update_interval,
            consecutive_failures=item.consecutive_failures,
            next_retry_at=item.next_retry_at,
            last_crawled_at=item.last_crawled_at,
            updated_at=item.updated_at,
        )


class CrawlerFailureInventoryResponse(BaseModel):
    items: list[CrawlerFailureInventoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, inventory: DomainCrawlerFailureInventory
    ) -> "CrawlerFailureInventoryResponse":
        return cls(
            items=[
                CrawlerFailureInventoryItem.from_domain(item)
                for item in inventory.items
            ],
            total=inventory.total,
            limit=inventory.limit,
            offset=inventory.offset,
        )


class CrawlerWatchdogLifecycleObserved(BaseModel):
    queued: int = Field(ge=0)
    running_no_progress: int = Field(ge=0)
    running_with_progress: int = Field(ge=0)
    terminal: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, lifecycle: DomainWatchdogLifecycleSnapshot
    ) -> "CrawlerWatchdogLifecycleObserved":
        return cls(
            queued=lifecycle.queued,
            running_no_progress=lifecycle.running_no_progress,
            running_with_progress=lifecycle.running_with_progress,
            terminal=lifecycle.terminal,
        )


class CrawlerWatchdogMetricsResponse(BaseModel):
    observed_at: datetime
    zombies_reconciled: int = Field(ge=0)
    expired_killed: int = Field(ge=0)
    rescued: int = Field(ge=0)
    early_zombies_failed: int = Field(ge=0)
    long_running_failed: int = Field(ge=0)
    slots_released: int = Field(ge=0)
    lifecycle_observed: CrawlerWatchdogLifecycleObserved

    @classmethod
    def from_domain(
        cls, metrics: DomainWatchdogMetricsSnapshot
    ) -> "CrawlerWatchdogMetricsResponse":
        return cls(
            observed_at=metrics.observed_at,
            zombies_reconciled=metrics.zombies_reconciled,
            expired_killed=metrics.expired_killed,
            rescued=metrics.rescued,
            early_zombies_failed=metrics.early_zombies_failed,
            long_running_failed=metrics.long_running_failed,
            slots_released=metrics.slots_released,
            lifecycle_observed=CrawlerWatchdogLifecycleObserved.from_domain(
                metrics.lifecycle_observed
            ),
        )


class CrawlerWatchdogStatusResponse(BaseModel):
    last_cleanup_at: datetime | None
    metrics: CrawlerWatchdogMetricsResponse | None
    recent_interventions: CrawlerRecentFailuresResponse

    @classmethod
    def from_domain(
        cls,
        *,
        snapshot: DomainWatchdogStatusSnapshot,
        recent_interventions: DomainCrawlerRecentFailures,
    ) -> "CrawlerWatchdogStatusResponse":
        return cls(
            last_cleanup_at=snapshot.last_cleanup_at,
            metrics=CrawlerWatchdogMetricsResponse.from_domain(snapshot.metrics)
            if snapshot.metrics is not None
            else None,
            recent_interventions=CrawlerRecentFailuresResponse.from_domain(
                recent_interventions
            ),
        )


class CrawlerWebsiteProcessingAggregateItem(BaseModel):
    website_id: UUID
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    update_interval: UpdateInterval | None
    total_runs: int = Field(ge=0)
    terminal_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    pages_crawled: int = Field(ge=0)
    files_downloaded: int = Field(ge=0)
    pages_hash_retained: int = Field(ge=0)
    files_hash_retained: int = Field(ge=0)
    pages_source_retained: int = Field(ge=0)
    files_too_large_skipped: int = Field(ge=0)
    pages_failed: int = Field(ge=0)
    files_failed: int = Field(ge=0)
    schedule_frequency_weight: float = Field(
        ge=0,
        description="Schedule multiplier used for crawler load-pressure ranking.",
    )
    indexed_content_count: int = Field(
        ge=0,
        description="Fetched, downloaded, and retained page/file count in the window.",
    )
    retention_rate: float = Field(
        ge=0,
        le=1,
        description="Share of indexed content retained without fetching or rewriting.",
    )
    cost_pressure_score: float = Field(
        ge=0,
        description="Schedule-weighted fetched page and file count for load ranking.",
    )
    embedding_input_tokens: int | None = Field(default=None, ge=0)
    embedding_total_cost_usd: str | None = None
    latest_embedding_model_name_snapshot: str | None = None
    latest_embedding_model_litellm_name_snapshot: str | None = None
    latest_embedding_model_provider_snapshot: str | None = None
    latest_embedding_input_tokens: int | None = Field(default=None, ge=0)
    latest_embedding_total_cost_usd: str | None = None
    latest_embedding_usage_source: str | None = None

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerWebsiteProcessingAggregateItem
    ) -> "CrawlerWebsiteProcessingAggregateItem":
        return cls(
            website_id=item.website_id,
            website_name=item.website_name,
            tenant_id=item.tenant_id,
            tenant_display_name=item.tenant_display_name,
            update_interval=item.update_interval,
            total_runs=item.total_runs,
            terminal_runs=item.terminal_runs,
            failed_runs=item.failed_runs,
            pages_crawled=item.pages_crawled,
            files_downloaded=item.files_downloaded,
            pages_hash_retained=item.pages_hash_retained,
            files_hash_retained=item.files_hash_retained,
            pages_source_retained=item.pages_source_retained,
            files_too_large_skipped=item.files_too_large_skipped,
            pages_failed=item.pages_failed,
            files_failed=item.files_failed,
            schedule_frequency_weight=item.schedule_frequency_weight,
            indexed_content_count=item.indexed_content_count,
            retention_rate=item.retention_rate,
            cost_pressure_score=item.cost_pressure_score,
            embedding_input_tokens=item.embedding_input_tokens,
            embedding_total_cost_usd=(
                str(item.embedding_total_cost_usd)
                if item.embedding_total_cost_usd is not None
                else None
            ),
            latest_embedding_model_name_snapshot=(
                item.latest_embedding_model_name_snapshot
            ),
            latest_embedding_model_litellm_name_snapshot=(
                item.latest_embedding_model_litellm_name_snapshot
            ),
            latest_embedding_model_provider_snapshot=(
                item.latest_embedding_model_provider_snapshot
            ),
            latest_embedding_input_tokens=item.latest_embedding_input_tokens,
            latest_embedding_total_cost_usd=(
                str(item.latest_embedding_total_cost_usd)
                if item.latest_embedding_total_cost_usd is not None
                else None
            ),
            latest_embedding_usage_source=item.latest_embedding_usage_source,
        )


class CrawlerWebsiteProcessingAggregateResponse(BaseModel):
    items: list[CrawlerWebsiteProcessingAggregateItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    days: int = Field(ge=1, le=30)
    since: datetime
    until: datetime
    tenant_id: UUID | None

    @classmethod
    def from_domain(
        cls, aggregate: DomainCrawlerWebsiteProcessingAggregate
    ) -> "CrawlerWebsiteProcessingAggregateResponse":
        return cls(
            items=[
                CrawlerWebsiteProcessingAggregateItem.from_domain(item)
                for item in aggregate.items
            ],
            total=aggregate.total,
            limit=aggregate.limit,
            offset=aggregate.offset,
            days=aggregate.days,
            since=aggregate.since,
            until=aggregate.until,
            tenant_id=aggregate.tenant_id,
        )
