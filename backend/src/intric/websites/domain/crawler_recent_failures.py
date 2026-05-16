from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason

# Keep this deny-by-default. A newly introduced failure outcome should not appear
# in admin failure inventory until its product meaning is reviewed here; success
# and retention outcomes are deliberately omitted.
RECENT_FAILURE_OUTCOME_CODES: frozenset[CrawlOutcomeCode] = frozenset(
    {
        CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
        CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES,
        CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
        CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED,
        CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
        CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED,
        CrawlOutcomeCode.CRAWL_DIRECT_ENQUEUE_FAILED,
        CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT,
        CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR,
        CrawlOutcomeCode.CRAWL_HEARTBEAT_FAILED,
        CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
        CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING,
        CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
    }
)

WATCHDOG_INTERVENTION_OUTCOME_CODES: frozenset[CrawlOutcomeCode] = frozenset(
    {
        CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
        CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED,
        CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
    }
)


@dataclass(frozen=True, slots=True)
class CrawlerRecentFailureItem:
    crawl_run_id: UUID
    job_id: UUID | None
    website_id: UUID
    website_name: str | None
    tenant_id: UUID
    tenant_display_name: str | None
    outcome_code: CrawlOutcomeCode
    failure_summary: Mapping[FailureReason, int] | None
    finished_at: datetime
    pages_crawled: int | None
    files_downloaded: int | None
    pages_failed: int | None
    files_failed: int | None
    pages_source_retained: int | None
    pages_hash_retained: int | None
    files_hash_retained: int | None
    files_too_large_skipped: int | None


@dataclass(frozen=True, slots=True)
class CrawlerRecentFailures:
    items: tuple[CrawlerRecentFailureItem, ...]
    total: int
    limit: int
    offset: int
    days: int
    since: datetime
    until: datetime
