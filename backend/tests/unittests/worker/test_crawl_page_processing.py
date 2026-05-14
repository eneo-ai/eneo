from collections.abc import Sequence
from uuid import uuid4

import pytest

from intric.crawler.parse_html import CrawledPage
from intric.websites.domain.crawl_outcome import FailureReason
from intric.worker.crawl.heartbeat import HeartbeatFailedError, JobPreemptedError
from intric.worker.crawl.page_processing import (
    HeartbeatFailedPageProcessingAbort,
    PageProcessingAbortReason,
    PageProcessingSuccess,
    PreemptedPageProcessingAbort,
    process_pages,
)
from intric.worker.crawl.persistence import CrawlPageData, PersistBatchResult


class _RecordingPersister:
    def __init__(self, results: Sequence[PersistBatchResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, page_buffer: list[CrawlPageData]) -> PersistBatchResult:
        self.calls.append(tuple(page["url"] for page in page_buffer))
        assert self._results
        return self._results.pop(0)


async def _heartbeat_ok() -> None:
    return None


class _FailingHeartbeat:
    def __init__(self, fail_on_call: int, exc: Exception) -> None:
        self.fail_on_call = fail_on_call
        self.exc = exc
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise self.exc


def _page(url: str) -> CrawledPage:
    return CrawledPage(url=url, title=url, content=f"content for {url}")


@pytest.mark.asyncio
async def test_process_pages_batches_pages_and_accumulates_success_counts() -> None:
    persister = _RecordingPersister(
        (
            PersistBatchResult(persisted_urls=("https://example.test/1",)),
            PersistBatchResult(
                persisted_urls=("https://example.test/3",),
                retained_urls=("https://example.test/2",),
            ),
        )
    )

    result = await process_pages(
        pages=iter(
            (
                _page("https://example.test/1"),
                _page("https://example.test/2"),
                _page("https://example.test/3"),
            )
        ),
        source_retained_urls=frozenset(),
        batch_size=2,
        heartbeat_tick=_heartbeat_ok,
        persist_pages=persister,
    )

    assert isinstance(result, PageProcessingSuccess)
    assert result.pages_crawled == 3
    assert result.pages_persisted == 2
    assert result.pages_hash_retained == 1
    assert result.pages_failed == 0
    assert result.cleanup_protected_titles == frozenset(
        {
            "https://example.test/1",
            "https://example.test/2",
            "https://example.test/3",
        }
    )
    assert persister.calls == [
        ("https://example.test/1", "https://example.test/2"),
        ("https://example.test/3",),
    ]


@pytest.mark.asyncio
async def test_process_pages_retains_source_urls_when_no_pages_are_fetched() -> None:
    persister = _RecordingPersister(())

    result = await process_pages(
        pages=iter(()),
        source_retained_urls=frozenset(
            {
                "https://example.test/a",
                "https://example.test/b",
                "https://example.test/c",
            }
        ),
        batch_size=2,
        heartbeat_tick=_heartbeat_ok,
        persist_pages=persister,
    )

    assert isinstance(result, PageProcessingSuccess)
    assert result.pages_crawled == 0
    assert result.pages_source_retained == 3
    assert result.cleanup_protected_titles == frozenset(
        {
            "https://example.test/a",
            "https://example.test/b",
            "https://example.test/c",
        }
    )
    assert persister.calls == []


@pytest.mark.asyncio
async def test_process_pages_aggregates_failures_across_batches() -> None:
    persister = _RecordingPersister(
        (
            PersistBatchResult(
                persisted_urls=("https://example.test/1",),
                failures_by_reason={
                    FailureReason.EMPTY_CONTENT: ("https://example.test/2",),
                },
            ),
            PersistBatchResult(
                failures_by_reason={
                    FailureReason.EMPTY_CONTENT: ("https://example.test/3",),
                    FailureReason.DB_ERROR: ("https://example.test/4",),
                },
            ),
        )
    )

    result = await process_pages(
        pages=iter(
            (
                _page("https://example.test/1"),
                _page("https://example.test/2"),
                _page("https://example.test/3"),
                _page("https://example.test/4"),
            )
        ),
        source_retained_urls=frozenset(),
        batch_size=2,
        heartbeat_tick=_heartbeat_ok,
        persist_pages=persister,
    )

    assert isinstance(result, PageProcessingSuccess)
    assert result.pages_crawled == 4
    assert result.pages_persisted == 1
    assert result.pages_failed == 3
    assert result.failed_titles == frozenset(
        {
            "https://example.test/2",
            "https://example.test/3",
            "https://example.test/4",
        }
    )
    assert result.failure_counts == {
        FailureReason.EMPTY_CONTENT: 2,
        FailureReason.DB_ERROR: 1,
    }


@pytest.mark.asyncio
async def test_process_pages_heartbeat_abort_preserves_legacy_page_count() -> None:
    heartbeat = _FailingHeartbeat(
        fail_on_call=2,
        exc=HeartbeatFailedError(consecutive_failures=3, max_failures=3),
    )
    persister = _RecordingPersister(())

    result = await process_pages(
        pages=iter(
            (
                _page("https://example.test/1"),
                _page("https://example.test/2"),
                _page("https://example.test/3"),
            )
        ),
        source_retained_urls=frozenset(),
        batch_size=10,
        heartbeat_tick=heartbeat,
        persist_pages=persister,
    )

    assert isinstance(result, HeartbeatFailedPageProcessingAbort)
    assert result.reason is PageProcessingAbortReason.HEARTBEAT_FAILED
    assert result.pages_crawled == 2
    assert result.consecutive_failures == 3
    assert persister.calls == []


@pytest.mark.asyncio
async def test_process_pages_heartbeat_abort_after_flushed_batch_keeps_pending_buffer_unflushed() -> (
    None
):
    heartbeat = _FailingHeartbeat(
        fail_on_call=4,
        exc=HeartbeatFailedError(consecutive_failures=4, max_failures=4),
    )
    persister = _RecordingPersister(
        (
            PersistBatchResult(
                persisted_urls=(
                    "https://example.test/1",
                    "https://example.test/2",
                )
            ),
        )
    )

    result = await process_pages(
        pages=iter(
            (
                _page("https://example.test/1"),
                _page("https://example.test/2"),
                _page("https://example.test/3"),
                _page("https://example.test/4"),
                _page("https://example.test/5"),
            )
        ),
        source_retained_urls=frozenset(),
        batch_size=2,
        heartbeat_tick=heartbeat,
        persist_pages=persister,
    )

    assert isinstance(result, HeartbeatFailedPageProcessingAbort)
    assert result.pages_crawled == 4
    assert result.consecutive_failures == 4
    assert persister.calls == [
        ("https://example.test/1", "https://example.test/2"),
    ]


@pytest.mark.asyncio
async def test_process_pages_preemption_abort_does_not_flush_pending_buffer() -> None:
    heartbeat = _FailingHeartbeat(
        fail_on_call=3,
        exc=JobPreemptedError(job_id=uuid4()),
    )
    persister = _RecordingPersister(())

    result = await process_pages(
        pages=iter(
            (
                _page("https://example.test/1"),
                _page("https://example.test/2"),
                _page("https://example.test/3"),
            )
        ),
        source_retained_urls=frozenset(),
        batch_size=10,
        heartbeat_tick=heartbeat,
        persist_pages=persister,
    )

    assert isinstance(result, PreemptedPageProcessingAbort)
    assert result.reason is PageProcessingAbortReason.PREEMPTED_DURING_CRAWL
    assert result.pages_crawled == 3
    assert persister.calls == []
