from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from intric.main.models import Status
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
from intric.websites.domain.crawler_active_inventory import (
    CrawlerActiveInventory as DomainCrawlerActiveInventory,
)
from intric.websites.domain.crawler_active_inventory import (
    CrawlerActiveInventoryItem as DomainCrawlerActiveInventoryItem,
)
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
from intric.websites.domain.website import UpdateInterval


class CrawlerActiveInventoryItem(BaseModel):
    job_id: UUID
    crawl_run_id: UUID | None
    website_id: UUID | None
    website_name: str | None
    tenant_id: UUID | None
    tenant_display_name: str | None
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
