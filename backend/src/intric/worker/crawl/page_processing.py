from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from intric.crawler.parse_html import CrawledPage
from intric.websites.domain.crawl_outcome import FailureReason
from intric.worker.crawl.heartbeat import HeartbeatFailedError, JobPreemptedError
from intric.worker.crawl.persistence import CrawlPageData, PersistBatchResult


def _empty_failure_counts() -> dict[FailureReason, int]:
    return {}


class PageProcessingAbortReason(StrEnum):
    HEARTBEAT_FAILED = "heartbeat_failed"
    PREEMPTED_DURING_CRAWL = "preempted_during_crawl"


@dataclass(frozen=True, slots=True)
class HeartbeatFailedPageProcessingAbort:
    pages_crawled: int
    consecutive_failures: int
    reason: Literal[PageProcessingAbortReason.HEARTBEAT_FAILED] = (
        PageProcessingAbortReason.HEARTBEAT_FAILED
    )


@dataclass(frozen=True, slots=True)
class PreemptedPageProcessingAbort:
    pages_crawled: int
    reason: Literal[PageProcessingAbortReason.PREEMPTED_DURING_CRAWL] = (
        PageProcessingAbortReason.PREEMPTED_DURING_CRAWL
    )


@dataclass(frozen=True, slots=True)
class PageProcessingSuccess:
    pages_crawled: int
    pages_persisted: int
    pages_failed: int
    pages_hash_retained: int
    pages_source_retained: int
    cleanup_protected_titles: frozenset[str]
    failed_titles: frozenset[str]
    failure_counts: Mapping[FailureReason, int] = field(
        default_factory=_empty_failure_counts
    )


PageProcessingAbort = HeartbeatFailedPageProcessingAbort | PreemptedPageProcessingAbort
PageProcessingOutcome = PageProcessingSuccess | PageProcessingAbort
HeartbeatTick = Callable[[], Awaitable[None]]
PagePersister = Callable[[list[CrawlPageData]], Awaitable[PersistBatchResult]]


async def process_pages(
    *,
    pages: Iterable[CrawledPage],
    source_retained_urls: frozenset[str],
    batch_size: int,
    heartbeat_tick: HeartbeatTick,
    persist_pages: PagePersister,
) -> PageProcessingOutcome:
    """Abort results count the triggering page without buffering or persisting it."""

    page_buffer: list[CrawlPageData] = []
    cleanup_protected_titles: set[str] = set(source_retained_urls)
    failed_titles: set[str] = set()
    failure_counts: dict[FailureReason, int] = defaultdict(int)
    pages_crawled = 0
    pages_failed = 0
    pages_hash_retained = 0
    pages_persisted = 0

    async def flush_buffer() -> None:
        nonlocal pages_failed, pages_hash_retained, pages_persisted
        if not page_buffer:
            return

        batch_result = await persist_pages(page_buffer)
        cleanup_protected_titles.update(batch_result.cleanup_protected_titles)
        failed_titles.update(batch_result.failed_urls)
        for reason, urls in batch_result.failures_by_reason.items():
            failure_counts[reason] += len(urls)
        pages_failed += batch_result.failed_count
        pages_hash_retained += batch_result.retained_count
        pages_persisted += batch_result.persisted_count
        page_buffer.clear()

    for page in pages:
        pages_crawled += 1
        try:
            await heartbeat_tick()
        except HeartbeatFailedError as exc:
            return HeartbeatFailedPageProcessingAbort(
                pages_crawled=pages_crawled,
                consecutive_failures=exc.consecutive_failures,
            )
        except JobPreemptedError:
            return PreemptedPageProcessingAbort(
                pages_crawled=pages_crawled,
            )

        page_buffer.append({"url": page.url, "content": page.content})
        if len(page_buffer) >= batch_size:
            await flush_buffer()

    await flush_buffer()

    return PageProcessingSuccess(
        pages_crawled=pages_crawled,
        pages_persisted=pages_persisted,
        pages_failed=pages_failed,
        pages_hash_retained=pages_hash_retained,
        pages_source_retained=len(source_retained_urls),
        cleanup_protected_titles=frozenset(cleanup_protected_titles),
        failed_titles=frozenset(failed_titles),
        failure_counts=dict(failure_counts),
    )
