from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason
from intric.websites.domain.crawler_recent_failures import (
    CrawlerRecentFailureItem as DomainCrawlerRecentFailureItem,
)
from intric.websites.domain.crawler_recent_failures import (
    CrawlerRecentFailures as DomainCrawlerRecentFailures,
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
