import asyncio

from eneo.worker.crawl_tasks import (
    _ByteBoundedQueue,
    _crawl_was_successful,
    _should_store_sitemap_state,
)


async def test_byte_bounded_queue_applies_backpressure_across_items() -> None:
    queue = _ByteBoundedQueue[str](max_items=10, max_bytes=10)
    await queue.put("first", weight=8)
    blocked_put = asyncio.create_task(queue.put("second", weight=4))
    await asyncio.sleep(0)

    assert not blocked_put.done()
    assert await queue.get() == "first"
    await blocked_put
    assert await queue.get() == "second"


def test_unchanged_sitemap_skip_is_a_success_even_without_existing_pages() -> None:
    assert _crawl_was_successful(
        pages=0,
        unchanged_pages=0,
        files=0,
        failed_pages=0,
        failed_files=0,
        sitemap_skipped=True,
    )


def test_sitemap_state_requires_a_failure_free_successful_crawl() -> None:
    common = {
        "has_new_state": True,
        "crawl_is_partial": False,
        "sitemap_skipped": False,
        "crawl_successful": True,
    }

    assert _should_store_sitemap_state(**common, total_failed=0)
    assert not _should_store_sitemap_state(**common, total_failed=1)
    assert not _should_store_sitemap_state(
        **{**common, "crawl_successful": False}, total_failed=0
    )
    assert not _should_store_sitemap_state(
        **{**common, "crawl_is_partial": True}, total_failed=0
    )
