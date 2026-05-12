from collections.abc import Mapping
from enum import Enum
from typing import Literal

CrawlOutcomeCrawlType = Literal["crawl", "sitemap"]
CrawlTerminationReason = Literal["completed", "timeout"]


class FailureReason(str, Enum):
    EMPTY_CONTENT = "EMPTY_CONTENT"
    NO_CHUNKS = "NO_CHUNKS"
    EMBEDDING_TIMEOUT = "EMBEDDING_TIMEOUT"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    EMBEDDING_BATCH_LIMIT = "EMBEDDING_BATCH_LIMIT"
    DB_ERROR = "DB_ERROR"
    NO_EMBEDDING_MODEL = "NO_EMBEDDING_MODEL"
    MISSING_PROVIDER = "MISSING_PROVIDER"


class CrawlOutcomeCode(str, Enum):
    CRAWL_DUPLICATE_SKIPPED = "CRAWL_DUPLICATE_SKIPPED"
    CRAWL_NO_PAGES_RETURNED = "CRAWL_NO_PAGES_RETURNED"
    CRAWL_SITEMAP_NO_PAGES = "CRAWL_SITEMAP_NO_PAGES"
    CRAWL_TIMEOUT_NO_PAGES = "CRAWL_TIMEOUT_NO_PAGES"
    CRAWL_MAX_AGE_EXCEEDED = "CRAWL_MAX_AGE_EXCEEDED"
    CRAWL_SOURCE_RETENTION_ONLY = "CRAWL_SOURCE_RETENTION_ONLY"
    CRAWL_ALL_UNCHANGED = "CRAWL_ALL_UNCHANGED"
    CRAWL_PARTIAL_TIMEOUT = "CRAWL_PARTIAL_TIMEOUT"
    CRAWL_SHUTDOWN_ERROR = "CRAWL_SHUTDOWN_ERROR"
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


def classify_crawl_outcome(
    *,
    crawl_type: CrawlOutcomeCrawlType,
    is_partial: bool,
    termination_reason: CrawlTerminationReason,
    pages_count: int,
    files_count: int = 0,
    source_retained_count: int,
    pages_hash_retained: int = 0,
    files_hash_retained: int = 0,
    failure_summary: Mapping[str, int] | None,
    pages_failed: int | None,
    files_failed: int | None,
) -> CrawlOutcomeCode | None:
    # Worker-time classifier for newly written crawl runs. Keep shared outcome
    # rules aligned with the read-side legacy fallback in crawl_models.py.
    has_output = pages_count > 0 or files_count > 0 or source_retained_count > 0
    has_failures = _has_failures(
        failure_summary=failure_summary,
        pages_failed=pages_failed,
        files_failed=files_failed,
    )
    if termination_reason == "timeout" and not has_output:
        return CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES

    if termination_reason == "completed" and not has_output:
        if crawl_type == "sitemap":
            return CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES
        return CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED

    if termination_reason == "timeout" or is_partial:
        return CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT

    if (
        source_retained_count > 0
        and pages_count == 0
        and files_count == 0
        and not has_failures
    ):
        return CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY

    if (
        pages_count + files_count > 0
        and pages_hash_retained + files_hash_retained == pages_count + files_count
        and not has_failures
    ):
        return CrawlOutcomeCode.CRAWL_ALL_UNCHANGED

    if failure_summary:
        if _has_embedding_config_failure(failure_summary):
            return CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING
        return CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES

    if (pages_failed or 0) + (files_failed or 0) > 0:
        return CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES

    return None


def _has_failures(
    *,
    failure_summary: Mapping[str, int] | None,
    pages_failed: int | None,
    files_failed: int | None,
) -> bool:
    return bool(failure_summary) or (pages_failed or 0) + (files_failed or 0) > 0


def _has_embedding_config_failure(failure_summary: Mapping[str, int]) -> bool:
    return (
        FailureReason.NO_EMBEDDING_MODEL.value in failure_summary
        or FailureReason.MISSING_PROVIDER.value in failure_summary
    )
