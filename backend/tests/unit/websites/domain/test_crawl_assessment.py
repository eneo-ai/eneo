import pytest

from eneo.websites.domain.crawl_assessment import (
    MINOR_FAILURE_SHARE,
    crawl_is_minor_partial,
    is_blocked_reason,
)
from eneo.websites.domain.crawl_run import CrawlFailureCode

# Shared with the frontend badge logic (crawlRunState.test.ts keeps a copy):
# (id, failure_code, pages_crawled, pages_unchanged, files_downloaded,
#  files_unchanged, pages_failed, files_failed, minor)
MINOR_PARTIAL_CASES = [
    ("resources-missing", "resources_missing", 0, 0, 0, 0, 900, 0, True),
    ("page-limit", "page_limit_reached", 162, 0, 0, 0, 0, 0, True),
    ("content-skipped", "content_skipped", 357, 0, 0, 0, 1, 0, True),
    ("one-in-358", "processing_failed", 340, 17, 2, 0, 1, 0, True),
    ("exactly-five-percent", "processing_failed", 19, 0, 0, 0, 1, 0, True),
    ("just-over-five-percent", "processing_failed", 18, 0, 0, 0, 1, 0, False),
    ("unchanged-counts-as-items", "processing_failed", 0, 95, 0, 0, 5, 0, True),
    ("files-count-too", "processing_failed", 0, 0, 38, 0, 0, 2, True),
    ("half-failed", "processing_failed", 5, 0, 0, 0, 5, 0, False),
    ("blocked-is-never-minor", "remote_blocked", 85, 0, 0, 0, 0, 1, False),
    ("unreachable-is-never-minor", "remote_unreachable", 500, 0, 0, 0, 1, 0, False),
    ("timed-out-is-never-minor", "timed_out", 500, 0, 0, 0, 1, 0, False),
    ("tenant-quota", "tenant_quota_exceeded", 500, 0, 0, 0, 1, 0, False),
    ("user-quota", "user_quota_exceeded", 500, 0, 0, 0, 1, 0, False),
    ("legacy-row-without-unchanged", "processing_failed", 357, None, 0, 0, 1, 0, False),
    (
        "legacy-row-without-any-counts",
        "processing_failed",
        None,
        None,
        None,
        None,
        None,
        None,
        False,
    ),
    (
        "legacy-row-benign-code",
        "resources_missing",
        None,
        None,
        None,
        None,
        None,
        None,
        True,
    ),
    ("no-code", None, 357, 0, 0, 0, 1, 0, True),
]


@pytest.mark.parametrize(
    (
        "failure_code",
        "pages_crawled",
        "pages_unchanged",
        "files_downloaded",
        "files_unchanged",
        "pages_failed",
        "files_failed",
        "minor",
    ),
    [case[1:] for case in MINOR_PARTIAL_CASES],
    ids=[case[0] for case in MINOR_PARTIAL_CASES],
)
def test_minor_partial_rule(
    failure_code: str | None,
    pages_crawled: int | None,
    pages_unchanged: int | None,
    files_downloaded: int | None,
    files_unchanged: int | None,
    pages_failed: int | None,
    files_failed: int | None,
    minor: bool,
) -> None:
    assert (
        crawl_is_minor_partial(
            failure_code=failure_code,
            pages_crawled=pages_crawled,
            pages_unchanged=pages_unchanged,
            files_downloaded=files_downloaded,
            files_unchanged=files_unchanged,
            pages_failed=pages_failed,
            files_failed=files_failed,
        )
        is minor
    )


def test_minor_partial_accepts_enum_codes() -> None:
    assert crawl_is_minor_partial(
        failure_code=CrawlFailureCode.CONTENT_SKIPPED,
        pages_crawled=0,
        pages_unchanged=0,
        files_downloaded=0,
        files_unchanged=0,
        pages_failed=1,
        files_failed=0,
    )


def test_minor_share_is_five_percent() -> None:
    assert MINOR_FAILURE_SHARE == 0.05


@pytest.mark.parametrize(
    ("reason", "blocked"),
    [
        ("robots_disallowed", True),
        ("http_403", True),
        ("http_429", True),
        ("http_451", True),
        ("http_404", False),
        ("http_500", False),
        ("request_timeout", False),
    ],
)
def test_blocked_reasons(reason: str, blocked: bool) -> None:
    assert is_blocked_reason(reason) is blocked
