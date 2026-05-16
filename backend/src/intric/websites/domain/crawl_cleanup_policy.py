"""Cleanup policy classification for crawl terminal outcomes.

The mapping codifies current worker cleanup behavior:

- CLEANUP_ALLOWED means the source frontier is complete enough for stale cleanup.
- CLEANUP_SKIPPED_PARTIAL means the source frontier is incomplete, so cleanup
  must be skipped to avoid deleting still-valid blobs.
- CLEANUP_NOT_REACHED means the crawl did not reach a trustworthy cleanup point.
- CLEANUP_NOOP means the terminal outcome intentionally did not mutate content.
"""

from enum import Enum

from intric.websites.domain.crawl_outcome import CrawlOutcomeCode


class CleanupPolicy(str, Enum):
    CLEANUP_ALLOWED = "CLEANUP_ALLOWED"
    CLEANUP_SKIPPED_PARTIAL = "CLEANUP_SKIPPED_PARTIAL"
    CLEANUP_NOT_REACHED = "CLEANUP_NOT_REACHED"
    CLEANUP_NOOP = "CLEANUP_NOOP"


_CLEANUP_POLICY_BY_OUTCOME: dict[CrawlOutcomeCode, CleanupPolicy] = {
    CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED: CleanupPolicy.CLEANUP_NOOP,
    CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT: CleanupPolicy.CLEANUP_SKIPPED_PARTIAL,
    CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_DIRECT_ENQUEUE_FAILED: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY: CleanupPolicy.CLEANUP_ALLOWED,
    CrawlOutcomeCode.CRAWL_ALL_UNCHANGED: CleanupPolicy.CLEANUP_ALLOWED,
    CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY: CleanupPolicy.CLEANUP_NOT_REACHED,
    # Admin-initiated abort stops the worker before cleanup. The page set
    # the crawler had at the moment of abort is partial; running stale
    # cleanup against it would delete blobs that are still canonical.
    CrawlOutcomeCode.CRAWL_ABORTED: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT: CleanupPolicy.CLEANUP_SKIPPED_PARTIAL,
    CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR: CleanupPolicy.CLEANUP_NOT_REACHED,
    # Heartbeat-failure terminations stop the worker mid-crawl with no
    # guarantee that the page/file set is complete. Treat cleanup as
    # not-reached so stale-blob deletion does not run on a partial view.
    CrawlOutcomeCode.CRAWL_HEARTBEAT_FAILED: CleanupPolicy.CLEANUP_NOT_REACHED,
    CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES: CleanupPolicy.CLEANUP_ALLOWED,
    CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING: CleanupPolicy.CLEANUP_ALLOWED,
    CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR: CleanupPolicy.CLEANUP_NOT_REACHED,
}


def cleanup_policy_for_outcome(
    outcome_code: CrawlOutcomeCode | None,
) -> CleanupPolicy:
    if outcome_code is None:
        return CleanupPolicy.CLEANUP_ALLOWED

    return _CLEANUP_POLICY_BY_OUTCOME[outcome_code]
