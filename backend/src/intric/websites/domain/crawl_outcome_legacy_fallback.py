from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode, FailureReason


@dataclass(frozen=True, slots=True)
class LegacyCrawlOutcomeInput:
    status: Status | str | None
    result_location: str | None
    failure_summary: Mapping[FailureReason, int] | None
    pages_failed: int | None
    files_failed: int | None
    pages_hash_retained: int | None = None
    files_hash_retained: int | None = None
    files_too_large_skipped: int | None = None
    indexed_count: int | None = None


@dataclass(frozen=True, slots=True)
class LegacyCrawlOutcomeFallback:
    outcome_code: CrawlOutcomeCode | None
    metric_code: CrawlOutcomeCode | None


def derive_outcome_from_legacy_columns(
    legacy_input: LegacyCrawlOutcomeInput,
) -> LegacyCrawlOutcomeFallback:
    status_value = (
        legacy_input.status.value
        if isinstance(legacy_input.status, Status)
        else legacy_input.status
    )
    detail_lower = (
        legacy_input.result_location.strip().lower()
        if legacy_input.result_location
        else ""
    )
    affected_count = (legacy_input.pages_failed or 0) + (legacy_input.files_failed or 0)
    hash_retained_count = (legacy_input.pages_hash_retained or 0) + (
        legacy_input.files_hash_retained or 0
    )
    too_large_count = legacy_input.files_too_large_skipped or 0
    has_no_indexed_content = (
        legacy_input.indexed_count is None or legacy_input.indexed_count == 0
    )

    if status_value == Status.FAILED.value and detail_lower.startswith(
        "skipped duplicate crawl"
    ):
        return _with_metric(CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED)

    if legacy_input.failure_summary:
        if _has_embedding_config_failure(legacy_input.failure_summary):
            return _with_metric(CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING)

        return _with_metric(CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES)

    if status_value == Status.FAILED.value or status_value == Status.NOT_FOUND.value:
        if "no pages returned" in detail_lower:
            return _with_metric(CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED)

        if "timeout" in detail_lower or "timed out" in detail_lower:
            return _with_metric(CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES)

        return _with_metric(CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR)

    if (
        status_value == Status.COMPLETE.value
        and too_large_count > 0
        and has_no_indexed_content
    ):
        return _without_metric(CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY)

    if affected_count > 0:
        return _with_metric(CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES)

    if (
        status_value == Status.COMPLETE.value
        and legacy_input.indexed_count is not None
        and hash_retained_count > 0
        and legacy_input.indexed_count == 0
    ):
        return _without_metric(CrawlOutcomeCode.CRAWL_ALL_UNCHANGED)

    return LegacyCrawlOutcomeFallback(outcome_code=None, metric_code=None)


def _with_metric(code: CrawlOutcomeCode) -> LegacyCrawlOutcomeFallback:
    return LegacyCrawlOutcomeFallback(outcome_code=code, metric_code=code)


# Count-derived success outcomes keep old rows readable, but they should not
# inflate the legacy-fallback metric that tracks inferred failure explanations.
def _without_metric(code: CrawlOutcomeCode) -> LegacyCrawlOutcomeFallback:
    return LegacyCrawlOutcomeFallback(outcome_code=code, metric_code=None)


def _has_embedding_config_failure(failure_summary: Mapping[FailureReason, int]) -> bool:
    return (
        FailureReason.NO_EMBEDDING_MODEL in failure_summary
        or FailureReason.MISSING_PROVIDER in failure_summary
    )
