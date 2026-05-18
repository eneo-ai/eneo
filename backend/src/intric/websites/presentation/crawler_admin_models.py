from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from intric.main.models import Status
from intric.websites.domain.bulk_crawl_interval_change import (
    BULK_INTERVAL_MAX_WEBSITE_IDS,
    BulkIntervalRowFailureCode,
)
from intric.websites.domain.bulk_crawl_interval_change import (
    BulkIntervalChangeResult as DomainBulkIntervalChangeResult,
)
from intric.websites.domain.crawl_abort import CrawlAbortConflictCode
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.crawl_website_delete import CrawlWebsiteDeleteConflictCode
from intric.websites.domain.crawler_active_inventory import (
    CrawlerActiveInventory as DomainCrawlerActiveInventory,
)
from intric.websites.domain.crawler_active_inventory import (
    CrawlerActiveInventoryItem as DomainCrawlerActiveInventoryItem,
)
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventory as DomainCrawlerFailureInventory,
)
from intric.websites.domain.crawler_failure_inventory import (
    CrawlerFailureInventoryItem as DomainCrawlerFailureInventoryItem,
)
from intric.websites.domain.crawler_failure_inventory import CrawlerFailureState
from intric.websites.domain.crawler_recent_failures import (
    CrawlerRecentFailureItem as DomainCrawlerRecentFailureItem,
)
from intric.websites.domain.crawler_recent_failures import (
    CrawlerRecentFailures as DomainCrawlerRecentFailures,
)
from intric.websites.domain.crawler_scheduled_aggregate import (
    CrawlerScheduledAggregate as DomainCrawlerScheduledAggregate,
)
from intric.websites.domain.crawler_scheduled_aggregate import (
    CrawlerScheduledIntervalBucket as DomainCrawlerScheduledIntervalBucket,
)
from intric.websites.domain.crawler_tenant_website_inventory import (
    CrawlerTenantWebsiteInventory as DomainCrawlerTenantWebsiteInventory,
)
from intric.websites.domain.crawler_tenant_website_inventory import (
    CrawlerTenantWebsiteInventoryItem as DomainCrawlerTenantWebsiteInventoryItem,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    CrawlerWebsiteProcessingAggregate as DomainCrawlerWebsiteProcessingAggregate,
)
from intric.websites.domain.crawler_website_processing_aggregate import (
    CrawlerWebsiteProcessingAggregateItem as DomainCrawlerWebsiteProcessingAggregateItem,
)
from intric.websites.domain.website import UpdateInterval


class CrawlerAbortConflictResponse(BaseModel):
    error_code: CrawlAbortConflictCode
    detail: str


class CrawlerWebsiteDeleteConflictResponse(BaseModel):
    """409 payload for the admin website-delete flow.

    The current admin surface only refuses when an active crawl job
    exists for the website; the operator's recovery is to abort that
    job first and retry. Future conflict reasons (e.g. legal-hold) can
    extend `CrawlWebsiteDeleteConflictCode` without re-shaping the
    wire schema.
    """

    error_code: CrawlWebsiteDeleteConflictCode
    detail: str


class CrawlerBulkIntervalRequest(BaseModel):
    """Wire shape for the admin bulk-interval endpoint.

    The explicit website-id list stays capped until "select all matching
    filter" can be implemented with same-transaction filtering and
    per-website audit rows.
    """

    website_ids: list[UUID] = Field(
        min_length=1, max_length=BULK_INTERVAL_MAX_WEBSITE_IDS
    )
    update_interval: UpdateInterval


class CrawlerBulkIntervalAppliedRow(BaseModel):
    website_id: UUID
    website_name: str
    previous_update_interval: UpdateInterval
    new_update_interval: UpdateInterval
    failure_state_cleared: bool


class CrawlerBulkIntervalUnchangedRow(BaseModel):
    website_id: UUID
    website_name: str
    update_interval: UpdateInterval


class CrawlerBulkIntervalFailedRow(BaseModel):
    website_id: UUID
    code: BulkIntervalRowFailureCode


class CrawlerBulkIntervalResponse(BaseModel):
    """200-with-structured-payload outcome of the bulk-interval batch.

    Wire shape preserves per-row outcome so the admin UI can render
    a partial-success summary (e.g. "32 updated, 3 unchanged, 1
    failed") + drill into failures by id. Avoids 207 Multi-Status —
    the JS SDK doesn't benefit from polyglot status codes.
    """

    applied: list[CrawlerBulkIntervalAppliedRow]
    unchanged: list[CrawlerBulkIntervalUnchangedRow]
    failed: list[CrawlerBulkIntervalFailedRow]

    @classmethod
    def from_domain(
        cls, result: DomainBulkIntervalChangeResult
    ) -> "CrawlerBulkIntervalResponse":
        return cls(
            applied=[
                CrawlerBulkIntervalAppliedRow(
                    website_id=row.website_id,
                    website_name=row.website_name,
                    previous_update_interval=row.previous_update_interval,
                    new_update_interval=row.new_update_interval,
                    failure_state_cleared=row.failure_state_cleared,
                )
                for row in result.applied
            ],
            unchanged=[
                CrawlerBulkIntervalUnchangedRow(
                    website_id=row.website_id,
                    website_name=row.website_name,
                    update_interval=row.update_interval,
                )
                for row in result.unchanged
            ],
            failed=[
                CrawlerBulkIntervalFailedRow(
                    website_id=row.website_id,
                    code=row.code,
                )
                for row in result.failed
            ],
        )


class CrawlerActiveInventoryItem(BaseModel):
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

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerActiveInventoryItem
    ) -> "CrawlerActiveInventoryItem":
        return cls(
            job_id=item.job_id,
            crawl_run_id=item.crawl_run_id,
            website_id=item.website_id,
            website_name=item.website_name,
            space_id=item.space_id,
            space_name=item.space_name,
            collection_id=item.collection_id,
            collection_name=item.collection_name,
            user_started_by_id=item.user_started_by_id,
            user_started_by_email=item.user_started_by_email,
            update_interval=item.update_interval,
            tenant_id=item.tenant_id,
            tenant_display_name=item.tenant_display_name,
            status=item.status,
            lifecycle_state=item.lifecycle_state,
            is_abortable=item.is_abortable,
            job_created_at=item.job_created_at,
            job_updated_at=item.job_updated_at,
            crawl_run_created_at=item.crawl_run_created_at,
            pages_crawled=item.pages_crawled,
            files_downloaded=item.files_downloaded,
            pages_failed=item.pages_failed,
            files_failed=item.files_failed,
            pages_source_retained=item.pages_source_retained,
            pages_hash_retained=item.pages_hash_retained,
            files_hash_retained=item.files_hash_retained,
            files_too_large_skipped=item.files_too_large_skipped,
        )


class CrawlerActiveInventoryResponse(BaseModel):
    items: list[CrawlerActiveInventoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, inventory: DomainCrawlerActiveInventory
    ) -> "CrawlerActiveInventoryResponse":
        return cls(
            items=[
                CrawlerActiveInventoryItem.from_domain(item) for item in inventory.items
            ],
            total=inventory.total,
            limit=inventory.limit,
            offset=inventory.offset,
        )


class CrawlerTenantFailureInventoryItem(BaseModel):
    website_id: UUID
    website_url: str
    website_name: str | None
    state: CrawlerFailureState
    update_interval: UpdateInterval
    consecutive_failures: int = Field(ge=0)
    next_retry_at: datetime | None
    last_crawled_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerFailureInventoryItem
    ) -> "CrawlerTenantFailureInventoryItem":
        return cls(
            website_id=item.website_id,
            website_url=item.website_url,
            website_name=item.website_name,
            state=item.state,
            update_interval=item.update_interval,
            consecutive_failures=item.consecutive_failures,
            next_retry_at=item.next_retry_at,
            last_crawled_at=item.last_crawled_at,
            updated_at=item.updated_at,
        )


class CrawlerTenantFailureInventoryResponse(BaseModel):
    items: list[CrawlerTenantFailureInventoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, inventory: DomainCrawlerFailureInventory
    ) -> "CrawlerTenantFailureInventoryResponse":
        return cls(
            items=[
                CrawlerTenantFailureInventoryItem.from_domain(item)
                for item in inventory.items
            ],
            total=inventory.total,
            limit=inventory.limit,
            offset=inventory.offset,
        )


class CrawlerRecentFailureItem(BaseModel):
    crawl_run_id: UUID
    job_id: UUID | None
    website_id: UUID
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    outcome_code: CrawlOutcomeCode
    failure_summary: dict[FailureReason, int] | None
    finished_at: datetime
    pages_crawled: int | None
    files_downloaded: int | None
    pages_failed: int | None
    files_failed: int | None
    pages_source_retained: int | None
    pages_hash_retained: int | None
    files_hash_retained: int | None
    files_too_large_skipped: int | None
    embedding_model_name_snapshot: str | None
    embedding_model_litellm_name_snapshot: str | None
    embedding_model_provider_snapshot: str | None
    embedding_input_tokens: int | None = Field(default=None, ge=0)
    embedding_total_cost_usd: str | None = None
    embedding_usage_source: str | None

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerRecentFailureItem
    ) -> "CrawlerRecentFailureItem":
        return cls(
            crawl_run_id=item.crawl_run_id,
            job_id=item.job_id,
            website_id=item.website_id,
            website_name=item.website_name,
            tenant_id=item.tenant_id,
            tenant_display_name=item.tenant_display_name,
            outcome_code=item.outcome_code,
            failure_summary=dict(item.failure_summary)
            if item.failure_summary is not None
            else None,
            finished_at=item.finished_at,
            pages_crawled=item.pages_crawled,
            files_downloaded=item.files_downloaded,
            pages_failed=item.pages_failed,
            files_failed=item.files_failed,
            pages_source_retained=item.pages_source_retained,
            pages_hash_retained=item.pages_hash_retained,
            files_hash_retained=item.files_hash_retained,
            files_too_large_skipped=item.files_too_large_skipped,
            embedding_model_name_snapshot=item.embedding_model_name_snapshot,
            embedding_model_litellm_name_snapshot=(
                item.embedding_model_litellm_name_snapshot
            ),
            embedding_model_provider_snapshot=item.embedding_model_provider_snapshot,
            embedding_input_tokens=item.embedding_input_tokens,
            embedding_total_cost_usd=(
                str(item.embedding_total_cost_usd)
                if item.embedding_total_cost_usd is not None
                else None
            ),
            embedding_usage_source=item.embedding_usage_source,
        )


class CrawlerRecentFailuresResponse(BaseModel):
    """Canonical bounded outcome-filtered terminal feed for crawler admin pages."""

    items: list[CrawlerRecentFailureItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    days: int = Field(ge=1, le=30)
    since: datetime
    until: datetime

    @classmethod
    def from_domain(
        cls, failures: DomainCrawlerRecentFailures
    ) -> "CrawlerRecentFailuresResponse":
        return cls(
            items=[
                CrawlerRecentFailureItem.from_domain(item) for item in failures.items
            ],
            total=failures.total,
            limit=failures.limit,
            offset=failures.offset,
            days=failures.days,
            since=failures.since,
            until=failures.until,
        )


class CrawlerScheduledIntervalBucket(BaseModel):
    update_interval: UpdateInterval
    website_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, bucket: DomainCrawlerScheduledIntervalBucket
    ) -> "CrawlerScheduledIntervalBucket":
        return cls(
            update_interval=bucket.update_interval,
            website_count=bucket.website_count,
            total_size_bytes=bucket.total_size_bytes,
        )


class CrawlerScheduledAggregateResponse(BaseModel):
    buckets: list[CrawlerScheduledIntervalBucket]
    total_websites: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    unparseable_update_interval_website_count: int = Field(ge=0)
    unparseable_update_interval_total_size_bytes: int = Field(ge=0)
    tenant_id: UUID | None

    @classmethod
    def from_domain(
        cls, aggregate: DomainCrawlerScheduledAggregate
    ) -> "CrawlerScheduledAggregateResponse":
        return cls(
            buckets=[
                CrawlerScheduledIntervalBucket.from_domain(bucket)
                for bucket in aggregate.buckets
            ],
            total_websites=aggregate.total_websites,
            total_size_bytes=aggregate.total_size_bytes,
            unparseable_update_interval_website_count=(
                aggregate.unparseable_update_interval_website_count
            ),
            unparseable_update_interval_total_size_bytes=(
                aggregate.unparseable_update_interval_total_size_bytes
            ),
            tenant_id=aggregate.tenant_id,
        )


class CrawlerTenantWebsiteProcessingAggregateItem(BaseModel):
    website_id: UUID
    website_name: str | None
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
    embedding_input_tokens: int | None = Field(
        default=None,
        ge=0,
        description="Provider-reported embedding input tokens indexed in this window.",
    )
    embedding_total_cost_usd: str | None = Field(
        default=None,
        description="Run-time USD cost snapshot for provider-reported embedding usage.",
    )
    latest_embedding_model_name_snapshot: str | None = None
    latest_embedding_model_litellm_name_snapshot: str | None = None
    latest_embedding_model_provider_snapshot: str | None = None
    latest_embedding_input_tokens: int | None = Field(default=None, ge=0)
    latest_embedding_total_cost_usd: str | None = None
    latest_embedding_usage_source: str | None = None

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerWebsiteProcessingAggregateItem
    ) -> "CrawlerTenantWebsiteProcessingAggregateItem":
        return cls(
            website_id=item.website_id,
            website_name=item.website_name,
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


class CrawlerTenantWebsiteProcessingAggregateResponse(BaseModel):
    """Aggregate response for the Aktivitet tab.

    `low_retention_threshold` and `source_skip_drift_min_indexed` are
    surfaced alongside the items so the frontend can render the same
    Låg behållning / Source-skip-drift row badges (and the matching
    filter chips) without duplicating the constants. Backend owns the
    truth; the frontend reads them off the call it already makes.
    """

    items: list[CrawlerTenantWebsiteProcessingAggregateItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    days: int = Field(ge=1, le=30)
    since: datetime
    until: datetime
    low_retention_threshold: float = Field(gt=0.0, lt=1.0)
    source_skip_drift_min_indexed: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, aggregate: DomainCrawlerWebsiteProcessingAggregate
    ) -> "CrawlerTenantWebsiteProcessingAggregateResponse":
        from intric.websites.domain.crawler_website_processing_aggregate import (
            LOW_RETENTION_THRESHOLD,
            SOURCE_SKIP_DRIFT_MIN_INDEXED,
        )

        return cls(
            items=[
                CrawlerTenantWebsiteProcessingAggregateItem.from_domain(item)
                for item in aggregate.items
            ],
            total=aggregate.total,
            limit=aggregate.limit,
            offset=aggregate.offset,
            days=aggregate.days,
            since=aggregate.since,
            until=aggregate.until,
            low_retention_threshold=LOW_RETENTION_THRESHOLD,
            source_skip_drift_min_indexed=SOURCE_SKIP_DRIFT_MIN_INDEXED,
        )


class CrawlerTenantWebsiteInventoryItem(BaseModel):
    """Wire shape for one row of the tenant Webbplatser governance table.

    Mirrors the domain `CrawlerTenantWebsiteInventoryItem` with one
    rename: the domain `size_bytes` becomes `size` on the wire to match
    the byte-count naming used by the scheduled aggregate and processing
    aggregate responses. The `failure_state` field is nullable on the
    wire: a website with no classifier match is healthy. Ownership
    columns expose the website *creator* (the user who registered the
    website), not the user who most recently triggered a crawl — that's
    the active-inventory's job.
    """

    website_id: UUID
    url: str
    name: str | None
    created_at: datetime
    update_interval: UpdateInterval
    crawl_type: CrawlType
    download_files: bool
    requires_http_auth: bool
    http_auth_username: str | None
    failure_state: CrawlerFailureState | None
    consecutive_failures: int = Field(ge=0)
    next_retry_at: datetime | None
    last_crawled_at: datetime | None
    size: int = Field(ge=0)
    owner_user_id: UUID | None
    owner_email: str | None
    space_id: UUID | None
    space_name: str | None
    collection_id: UUID | None
    collection_name: str | None

    @classmethod
    def from_domain(
        cls, item: DomainCrawlerTenantWebsiteInventoryItem
    ) -> "CrawlerTenantWebsiteInventoryItem":
        return cls(
            website_id=item.website_id,
            url=item.url,
            name=item.name,
            created_at=item.created_at,
            update_interval=item.update_interval,
            crawl_type=item.crawl_type,
            download_files=item.download_files,
            requires_http_auth=item.requires_http_auth,
            http_auth_username=item.http_auth_username,
            failure_state=item.failure_state,
            consecutive_failures=item.consecutive_failures,
            next_retry_at=item.next_retry_at,
            last_crawled_at=item.last_crawled_at,
            size=item.size_bytes,
            owner_user_id=item.owner_user_id,
            owner_email=item.owner_email,
            space_id=item.space_id,
            space_name=item.space_name,
            collection_id=item.collection_id,
            collection_name=item.collection_name,
        )


class CrawlerTenantWebsiteInventoryResponse(BaseModel):
    items: list[CrawlerTenantWebsiteInventoryItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, inventory: DomainCrawlerTenantWebsiteInventory
    ) -> "CrawlerTenantWebsiteInventoryResponse":
        return cls(
            items=[
                CrawlerTenantWebsiteInventoryItem.from_domain(item)
                for item in inventory.items
            ],
            total=inventory.total,
            limit=inventory.limit,
            offset=inventory.offset,
        )
