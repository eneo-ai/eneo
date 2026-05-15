from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from intric.main.models import Status
from intric.websites.domain.crawl_abort import CrawlAbortConflictCode
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
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


class CrawlerActiveInventoryItem(BaseModel):
    job_id: UUID
    crawl_run_id: UUID | None
    website_id: UUID | None
    website_name: str | None
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
        description="Schedule multiplier used for crawler cost-pressure ranking.",
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
        description="Schedule-weighted changed/new page and file count for ranking.",
    )

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
        )


class CrawlerTenantWebsiteProcessingAggregateResponse(BaseModel):
    items: list[CrawlerTenantWebsiteProcessingAggregateItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    days: int = Field(ge=1, le=30)
    since: datetime
    until: datetime

    @classmethod
    def from_domain(
        cls, aggregate: DomainCrawlerWebsiteProcessingAggregate
    ) -> "CrawlerTenantWebsiteProcessingAggregateResponse":
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
        )
