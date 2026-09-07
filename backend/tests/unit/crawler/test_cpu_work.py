import asyncio
import threading

import pytest

from eneo.crawler.cpu_work import run_cpu_work
from eneo.crawler.extraction import extract_html


async def test_cancelled_cpu_work_retains_capacity_until_the_thread_finishes():
    release = threading.Event()
    started = [threading.Event(), threading.Event(), threading.Event()]

    def blocked(index):
        started[index].set()
        release.wait(timeout=5)
        return index

    first = asyncio.create_task(run_cpu_work(blocked, 0))
    second = asyncio.create_task(run_cpu_work(blocked, 1))
    third = None
    try:
        assert await asyncio.to_thread(started[0].wait, 2)
        assert await asyncio.to_thread(started[1].wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, timeout=0.2)
        third = asyncio.create_task(run_cpu_work(blocked, 2))
        await asyncio.sleep(0.05)
        assert not started[2].is_set()
        release.set()
        assert await asyncio.wait_for(third, timeout=2) == 2
        assert await second == 1
    finally:
        release.set()
        await asyncio.gather(
            first, second, *([third] if third else []), return_exceptions=True
        )


async def test_offloaded_extraction_preserves_content_and_late_links():
    html = (
        "<html><main><h1>Knowledge</h1>"
        + (
            '<a href="https://external.test/">External</a><a href="/duplicate">Duplicate</a>'
            * 10000
        )
        + '<a href="/new-descendant">New page</a></main></html>'
    )
    page = await run_cpu_work(extract_html, html, "https://example.test/")
    assert page == extract_html(html, "https://example.test/")
    assert "https://example.test/new-descendant" in page.links
