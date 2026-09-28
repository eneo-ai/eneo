"""Stale-content cleanup after a crawl only removes pages a clean, complete
crawl proved gone; a partial crawl or one with download errors keeps
everything."""

from eneo.worker.crawl_tasks import select_stale_titles

EXISTING = ["a", "b", "c", "d"]


def test_clean_crawl_removes_pages_not_seen():
    stale = select_stale_titles(
        EXISTING,
        crawled_titles=["a", "b"],
        failed_titles=["c"],
        is_partial=False,
        download_error_count=0,
    )
    assert stale == ["d"]


def test_failed_pages_are_never_stale():
    stale = select_stale_titles(
        EXISTING,
        crawled_titles=[],
        failed_titles=EXISTING,
        is_partial=False,
        download_error_count=0,
    )
    assert stale == []


def test_partial_crawl_keeps_everything():
    stale = select_stale_titles(
        EXISTING,
        crawled_titles=["a"],
        failed_titles=[],
        is_partial=True,
        download_error_count=0,
    )
    assert stale == []


def test_download_errors_keep_everything():
    stale = select_stale_titles(
        EXISTING,
        crawled_titles=["a"],
        failed_titles=[],
        is_partial=False,
        download_error_count=1,
    )
    assert stale == []
