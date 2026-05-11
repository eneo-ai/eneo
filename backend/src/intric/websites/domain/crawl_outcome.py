from enum import Enum


class CrawlOutcomeCode(str, Enum):
    CRAWL_DUPLICATE_SKIPPED = "CRAWL_DUPLICATE_SKIPPED"
    CRAWL_NO_PAGES_RETURNED = "CRAWL_NO_PAGES_RETURNED"
    CRAWL_SITEMAP_NO_PAGES = "CRAWL_SITEMAP_NO_PAGES"
    CRAWL_TIMEOUT_NO_PAGES = "CRAWL_TIMEOUT_NO_PAGES"
    CRAWL_MAX_AGE_EXCEEDED = "CRAWL_MAX_AGE_EXCEEDED"
    CRAWL_SOURCE_RETENTION_ONLY = "CRAWL_SOURCE_RETENTION_ONLY"
    CRAWL_COMPLETED_WITH_PAGE_FAILURES = "CRAWL_COMPLETED_WITH_PAGE_FAILURES"
    EMBEDDING_CONFIG_MISSING = "EMBEDDING_CONFIG_MISSING"
    UNKNOWN_CRAWL_ERROR = "UNKNOWN_CRAWL_ERROR"


def parse_crawl_outcome_code(
    value: str | CrawlOutcomeCode | None,
) -> CrawlOutcomeCode | None:
    if value is None or isinstance(value, CrawlOutcomeCode):
        return value

    try:
        return CrawlOutcomeCode(value)
    except ValueError:
        return CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR
