"""How a finished crawl is judged: failure codes and the minor-partial rule.

A crawl is ``partial`` as soon as one item failed, which is truthful but not
actionable on its own. These rules decide whether a partial run deserves
attention. The same rule is expressed in SQL for the admin overview and in
TypeScript for the run badges; the unit tests pin the shared cases.
"""

from __future__ import annotations

from eneo.websites.domain.crawl_run import CrawlFailureCode

BENIGN_RESOURCE_REASONS = frozenset(
    {"empty_content", "no_chunks", "unsupported_content_type", "http_304"}
)
"""Per-resource reasons that mean "nothing to index here", not "broken"."""

MISSING_RESOURCE_REASONS = frozenset({"http_404", "http_410"})
"""The resource is gone; the crawl itself was healthy."""

BLOCKED_REASON_PREFIXES = ("http_401", "http_403", "http_407", "http_429", "http_451")
"""HTTP statuses that say the remote refused us."""

BENIGN_FAILURE_CODES = frozenset(
    {
        CrawlFailureCode.RESOURCES_MISSING,
        CrawlFailureCode.PAGE_LIMIT_REACHED,
        CrawlFailureCode.CONTENT_SKIPPED,
    }
)
"""Partial outcomes that describe the site or its limits, not a malfunction."""

SEVERE_FAILURE_CODES = frozenset(
    {
        CrawlFailureCode.TENANT_QUOTA_EXCEEDED,
        CrawlFailureCode.USER_QUOTA_EXCEEDED,
        CrawlFailureCode.REMOTE_BLOCKED,
        CrawlFailureCode.REMOTE_UNREACHABLE,
        CrawlFailureCode.TIMED_OUT,
    }
)
"""Partial outcomes that need attention however few items failed."""

MINOR_FAILURE_SHARE = 0.05
"""Failed items may be at most this share of all items for a minor partial."""


def is_blocked_reason(reason: str) -> bool:
    return reason == "robots_disallowed" or reason.startswith(BLOCKED_REASON_PREFIXES)


def crawl_is_minor_partial(
    *,
    failure_code: CrawlFailureCode | str | None,
    pages_crawled: int | None,
    pages_unchanged: int | None,
    files_downloaded: int | None,
    files_unchanged: int | None,
    pages_failed: int | None,
    files_failed: int | None,
) -> bool:
    """Whether a partial crawl counts as completed with notes.

    Benign codes always do; severe codes never do. Otherwise the failed share
    of all items decides. Runs without recorded counters cannot qualify.
    """
    code = CrawlFailureCode(failure_code) if failure_code else None
    if code in BENIGN_FAILURE_CODES:
        return True
    if code in SEVERE_FAILURE_CODES:
        return False
    counters = (
        pages_crawled,
        pages_unchanged,
        files_downloaded,
        files_unchanged,
        pages_failed,
        files_failed,
    )
    if any(value is None for value in counters):
        return False
    failed = (pages_failed or 0) + (files_failed or 0)
    total = failed + sum(value or 0 for value in counters[:4])
    return failed <= MINOR_FAILURE_SHARE * total
