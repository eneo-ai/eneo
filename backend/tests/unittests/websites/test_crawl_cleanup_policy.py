import pytest

from intric.websites.domain.crawl_cleanup_policy import (
    CleanupPolicy,
    cleanup_policy_for_outcome,
)
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode


def test_every_crawl_outcome_has_cleanup_policy():
    for outcome_code in CrawlOutcomeCode:
        assert cleanup_policy_for_outcome(outcome_code) in CleanupPolicy


def test_success_without_diagnostic_outcome_allows_cleanup():
    assert cleanup_policy_for_outcome(None) == CleanupPolicy.CLEANUP_ALLOWED


@pytest.mark.parametrize(
    ("outcome_code", "expected_policy"),
    [
        (
            CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
            CleanupPolicy.CLEANUP_NOOP,
        ),
        (
            CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
            CleanupPolicy.CLEANUP_SKIPPED_PARTIAL,
        ),
        (
            CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_DIRECT_ENQUEUE_FAILED,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
            CleanupPolicy.CLEANUP_ALLOWED,
        ),
        (
            CrawlOutcomeCode.CRAWL_ALL_UNCHANGED,
            CleanupPolicy.CLEANUP_ALLOWED,
        ),
        (
            CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT,
            CleanupPolicy.CLEANUP_SKIPPED_PARTIAL,
        ),
        (
            CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
        (
            CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
            CleanupPolicy.CLEANUP_ALLOWED,
        ),
        (
            CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING,
            CleanupPolicy.CLEANUP_ALLOWED,
        ),
        (
            CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
            CleanupPolicy.CLEANUP_NOT_REACHED,
        ),
    ],
)
def test_cleanup_policy_matches_current_worker_cleanup_behavior(
    outcome_code: CrawlOutcomeCode,
    expected_policy: CleanupPolicy,
):
    # The mapping preserves current behavior from crawl_tasks.py:
    # _compute_stale_titles skips cleanup for partial crawls, while the
    # zero-output terminal branch returns before stale cleanup is reached.
    assert cleanup_policy_for_outcome(outcome_code) == expected_policy
