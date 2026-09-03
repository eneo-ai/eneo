import asyncio
import hashlib
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import pytest
from aiohttp import web

from eneo.crawler import python_engine
from eneo.crawler.engine import (
    ConditionalGet,
    CrawlEvent,
    CrawlFinished,
    CrawlLimits,
    CrawlRequest,
    FileDownloaded,
    FileFailed,
    PageCrawled,
    PageFailed,
    PageUnchanged,
)
from eneo.crawler.python_engine import (
    PythonCrawlEngine,
    _address_is_allowed,
    _reject_disallowed_literal,
    _UnsafeTarget,
)
from eneo.websites.domain.crawl_run import CrawlType


def _request(
    url: str,
    *,
    crawl_type: CrawlType = CrawlType.CRAWL,
    obey_robots: bool = False,
    max_response_bytes: int = 100_000,
    max_file_bytes: int = 10 * 1024 * 1024,
    max_items: int = 10,
    max_seconds: float = 10,
    download_files: bool = True,
    concurrency: int = 2,
    request_delay_seconds: float = 0,
    conditional_gets: tuple[ConditionalGet, ...] = (),
    conditional_gets_truncated: bool = False,
) -> CrawlRequest:
    return CrawlRequest(
        url=url,
        crawl_type=crawl_type,
        download_files=download_files,
        obey_robots=obey_robots,
        limits=CrawlLimits(
            max_items=max_items,
            max_seconds=max_seconds,
            request_timeout_seconds=2,
            max_response_bytes=max_response_bytes,
            max_file_bytes=max_file_bytes,
            concurrency=concurrency,
            request_delay_seconds=request_delay_seconds,
            retries=1,
        ),
        conditional_gets=conditional_gets,
        conditional_gets_truncated=conditional_gets_truncated,
    )


@asynccontextmanager
async def _serve(app: web.Application) -> AsyncIterator[str]:
    runner = web.AppRunner(app)
    await runner.setup()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(128)
    port = server_socket.getsockname()[1]
    site = web.SockSite(runner, server_socket)
    await site.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


async def test_crawl_emits_pages_incrementally_and_follows_scoped_links() -> None:
    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><h1>Start</h1><a href="/start/child">Barn</a></main>',
            content_type="text/html",
            headers={"ETag": '"one"'},
        )

    async def child(_: web.Request) -> web.Response:
        return web.Response(
            text="<main><h1>Barnsida</h1><p>Relevant innehåll</p></main>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/child", child)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start")
            )
        ]

    pages = [event for event in events if isinstance(event, PageCrawled)]
    assert [page.url for page in pages] == [
        f"{base_url}/start",
        f"{base_url}/start/child",
    ]
    assert pages[0].etag == '"one"'
    assert "Relevant innehåll" in pages[1].content
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=2, pages_failed=0
    )


async def test_page_fetches_refill_available_slots_before_the_slowest_finishes() -> (
    None
):
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    replacement_started = asyncio.Event()
    active = 0
    peak = 0

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text=(
                '<main><a href="/start/slow">Slow</a>'
                '<a href="/start/fast-1">Fast one</a>'
                '<a href="/start/fast-2">Fast two</a></main>'
            ),
            content_type="text/html",
        )

    async def child(request: web.Request) -> web.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            if request.path == "/start/slow":
                slow_started.set()
                await release_slow.wait()
            elif request.path == "/start/fast-1":
                await slow_started.wait()
            else:
                replacement_started.set()
            return web.Response(text="<main>ok</main>", content_type="text/html")
        finally:
            active -= 1

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/{name}", child)

    async with _serve(app) as base_url:

        async def collect() -> list[CrawlEvent]:
            return [
                event
                async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                    _request(
                        f"{base_url}/start",
                        max_items=4,
                        concurrency=2,
                        download_files=False,
                    )
                )
            ]

        crawl_task = asyncio.create_task(collect())
        replacement_started_in_time = True
        try:
            await asyncio.wait_for(replacement_started.wait(), timeout=0.1)
        except TimeoutError:
            replacement_started_in_time = False
        finally:
            release_slow.set()
        events = await asyncio.wait_for(crawl_task, timeout=1)

    assert replacement_started_in_time
    assert peak == 2
    assert {event.url for event in events if isinstance(event, PageCrawled)} == {
        f"{base_url}/start",
        f"{base_url}/start/slow",
        f"{base_url}/start/fast-1",
        f"{base_url}/start/fast-2",
    }
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=4, pages_failed=0
    )


async def test_page_refill_applies_one_delay_while_other_requests_finish() -> None:
    starts: dict[str, float] = {}

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text=(
                '<main><a href="/start/slow">Slow</a>'
                '<a href="/start/fast-1">Fast one</a>'
                '<a href="/start/fast-2">Fast two</a>'
                '<a href="/start/fast-3">Fast three</a></main>'
            ),
            content_type="text/html",
        )

    async def child(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        starts[name] = asyncio.get_running_loop().time()
        if name == "slow":
            await asyncio.sleep(0.01)
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/{name}", child)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    max_items=5,
                    concurrency=2,
                    request_delay_seconds=0.05,
                    download_files=False,
                )
            )
        ]

    assert starts["fast-2"] - starts["fast-1"] >= 0.04
    assert abs(starts["fast-3"] - starts["fast-2"]) < 0.02
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=5, pages_failed=0
    )


async def test_expired_refill_delay_does_not_spin_at_page_limit(monkeypatch) -> None:
    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text=(
                '<main><a href="/start/slow">Slow</a>'
                '<a href="/start/fast">Fast</a>'
                '<a href="/start/not-fetched">Not fetched</a></main>'
            ),
            content_type="text/html",
        )

    async def child(request: web.Request) -> web.Response:
        if request.match_info["name"] == "slow":
            await asyncio.sleep(0.15)
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/{name}", child)

    real_wait = asyncio.wait
    wait_spy = AsyncMock(wraps=real_wait)
    monkeypatch.setattr("eneo.crawler.python_engine.asyncio.wait", wait_spy)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    max_items=3,
                    concurrency=2,
                    request_delay_seconds=0.02,
                    download_files=False,
                )
            )
        ]

    assert wait_spy.await_count < 20
    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=3,
        pages_failed=0,
        reason="item_limit",
    )


async def test_page_limit_selection_is_independent_of_response_order() -> None:
    slow_sibling = "a"

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text=('<main><a href="/start/a">A</a><a href="/start/b">B</a></main>'),
            content_type="text/html",
        )

    async def sibling(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if name == slow_sibling:
            await asyncio.sleep(0.05)
        return web.Response(
            text=f'<main><a href="/start/{name}/child">Child</a></main>',
            content_type="text/html",
        )

    async def child(_: web.Request) -> web.Response:
        return web.Response(text="<main>child</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/{name}", sibling)
    app.router.add_get("/start/{name}/child", child)

    async with _serve(app) as base_url:

        async def selected_urls() -> list[str]:
            events = [
                event
                async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                    _request(
                        f"{base_url}/start",
                        max_items=4,
                        concurrency=2,
                        download_files=False,
                    )
                )
            ]
            return [event.url for event in events if isinstance(event, PageCrawled)]

        first_selection = await selected_urls()
        slow_sibling = "b"
        second_selection = await selected_urls()

    expected_selection = {
        f"{base_url}/start",
        f"{base_url}/start/a",
        f"{base_url}/start/b",
        f"{base_url}/start/a/child",
    }
    assert len(first_selection) == len(second_selection) == len(expected_selection)
    assert set(first_selection) == set(second_selection) == expected_selection


async def test_discovered_page_and_file_work_shares_the_configured_item_budget() -> (
    None
):
    requested_pages: list[str] = []
    requested_files: list[str] = []

    async def start(_: web.Request) -> web.Response:
        page_links = "".join(
            f'<a href="/start/page-{index}">Page {index}</a>' for index in range(2)
        )
        file_links = "".join(
            f'<a href="/files/document-{index}.pdf">Document {index}</a>'
            for index in range(100)
        )
        return web.Response(
            text=f"<main>{page_links}{file_links}</main>",
            content_type="text/html",
        )

    async def page(request: web.Request) -> web.Response:
        requested_pages.append(request.path)
        return web.Response(text="<main>Page</main>", content_type="text/html")

    async def file(request: web.Request) -> web.Response:
        requested_files.append(request.path)
        return web.Response(body=b"document", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/{name}", page)
    app.router.add_get("/files/{name}", file)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    max_items=6,
                    concurrency=2,
                )
            )
        ]

    assert len(requested_pages) == 2
    assert len(requested_files) == 3
    assert len([event for event in events if isinstance(event, FileDownloaded)]) == 3
    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=3,
        pages_failed=0,
        files_downloaded=3,
        reason="item_limit",
    )


async def test_item_budget_adapts_to_a_page_with_many_files() -> None:
    requested_files: list[str] = []

    async def start(_: web.Request) -> web.Response:
        links = "".join(
            f'<a href="/files/document-{index}.pdf">Document {index}</a>'
            for index in range(100)
        )
        return web.Response(text=f"<main>{links}</main>", content_type="text/html")

    async def file(request: web.Request) -> web.Response:
        requested_files.append(request.path)
        return web.Response(body=b"document", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/files/{name}", file)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", max_items=4)
            )
        ]

    assert len(requested_files) == 3
    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=1,
        pages_failed=0,
        files_downloaded=3,
        reason="item_limit",
    )


async def test_link_reorder_window_stays_bounded_behind_slow_page() -> None:
    concurrency = 2
    expected_window = concurrency * 2
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    window_filled = asyncio.Event()
    started_children: list[str] = []

    async def start(_: web.Request) -> web.Response:
        links = "".join(
            f'<a href="/start/page-{index}">Page {index}</a>' for index in range(20)
        )
        return web.Response(text=f"<main>{links}</main>", content_type="text/html")

    async def child(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        started_children.append(name)
        if len(started_children) >= expected_window:
            window_filled.set()
        if name == "page-0":
            slow_started.set()
            await release_slow.wait()
        else:
            await slow_started.wait()
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/start/{name}", child)

    async with _serve(app) as base_url:

        async def collect() -> list[CrawlEvent]:
            return [
                event
                async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                    _request(
                        f"{base_url}/start",
                        max_items=21,
                        concurrency=concurrency,
                        download_files=False,
                    )
                )
            ]

        crawl_task = asyncio.create_task(collect())
        try:
            await asyncio.wait_for(window_filled.wait(), timeout=1)
            await asyncio.sleep(0.05)
            assert len(started_children) == expected_window
        finally:
            release_slow.set()
        events = await asyncio.wait_for(crawl_task, timeout=2)

    assert len([event for event in events if isinstance(event, PageCrawled)]) == 21
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=21, pages_failed=0
    )


async def test_crawl_honors_robots_rules() -> None:
    async def robots(_: web.Request) -> web.Response:
        return web.Response(
            text="User-agent: *\nDisallow: /start/private",
            content_type="text/plain",
        )

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/start/private">Hemlig</a></main>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/start", start)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", obey_robots=True)
            )
        ]

    assert any(
        isinstance(event, PageFailed) and event.reason == "robots_disallowed"
        for event in events
    )
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=1, pages_failed=1
    )


async def test_sitemap_crawl_follows_nested_indexes_but_not_page_links() -> None:
    app = web.Application()

    async def sitemap_index(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{origin}/nested.xml</loc></sitemap>"
                "</sitemapindex>"
            ),
            content_type="application/xml",
        )

    async def nested(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{origin}/page</loc></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def page(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><h1>Sitemap page</h1><a href="/not-in-map">No</a></main>',
            content_type="text/html",
        )

    app.router.add_get("/sitemap.xml", sitemap_index)
    app.router.add_get("/nested.xml", nested)
    app.router.add_get("/page", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    pages = [event for event in events if isinstance(event, PageCrawled)]
    assert [page.url for page in pages] == [f"{base_url}/page"]
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=1, pages_failed=0
    )


async def test_sitemap_pages_and_linked_files_share_the_item_budget() -> None:
    requested_files: list[str] = []

    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{origin}/page/one</loc></url>"
                f"<url><loc>{origin}/page/two</loc></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def page(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        return web.Response(
            text=f'<main><a href="/files/{name}.pdf">Document</a></main>',
            content_type="text/html",
        )

    async def file(request: web.Request) -> web.Response:
        requested_files.append(request.path)
        return web.Response(body=b"document", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/page/{name}", page)
    app.router.add_get("/files/{name}", file)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/sitemap.xml",
                    crawl_type=CrawlType.SITEMAP,
                    max_items=4,
                )
            )
        ]

    assert len(requested_files) == 2
    assert len([event for event in events if isinstance(event, PageCrawled)]) == 2
    assert len([event for event in events if isinstance(event, FileDownloaded)]) == 2
    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=2,
        pages_failed=0,
        files_downloaded=2,
    )


async def test_sitemap_page_limit_ignores_known_non_page_urls() -> None:
    requested: list[str] = []

    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{origin}/encoded%2Ejpg</loc></url>"
                f"<url><loc>{origin}/app.webmanifest</loc></url>"
                f"<url><loc>{origin}/guide.pdf</loc></url>"
                f"<url><loc>{origin}/asset.jpg</loc></url>"
                f"<url><loc>{origin}/page</loc><lastmod>2026-09-03</lastmod></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def asset(request: web.Request) -> web.Response:
        requested.append(request.path)
        return web.Response(body=b"image", content_type="image/jpeg")

    async def page(request: web.Request) -> web.Response:
        requested.append(request.path)
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/asset.jpg", asset)
    app.router.add_get("/page", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/sitemap.xml",
                    crawl_type=CrawlType.SITEMAP,
                    max_items=1,
                )
            )
        ]

    assert requested == ["/page"]
    assert [event.url for event in events if isinstance(event, PageCrawled)] == [
        f"{base_url}/page"
    ]
    assert not any(isinstance(event, PageFailed) for event in events)
    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=1,
        pages_failed=0,
        sitemap_fingerprint=hashlib.sha256(
            f"{base_url}/page\t2026-09-03".encode()
        ).hexdigest(),
        sitemap_entries=1,
    )


async def test_sitemap_marks_only_an_additional_valid_page_as_truncated() -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{origin}/one</loc></url>"
                f"<url><loc>{origin}/two</loc></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def page(_: web.Request) -> web.Response:
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/{name}", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/sitemap.xml",
                    crawl_type=CrawlType.SITEMAP,
                    max_items=1,
                )
            )
        ]

    assert len([event for event in events if isinstance(event, PageCrawled)]) == 1
    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=1,
        pages_failed=0,
        reason="item_limit",
    )


async def test_conditional_frontier_keeps_known_children_when_seed_is_304() -> None:
    requested: list[str] = []

    async def not_modified(request: web.Request) -> web.Response:
        requested.append(request.path)
        assert request.headers["If-None-Match"] == '"known"'
        return web.Response(status=304)

    app = web.Application()
    app.router.add_get("/start", not_modified)
    app.router.add_get("/start/child", not_modified)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    conditional_gets=(
                        ConditionalGet(f"{base_url}/start", etag='"known"'),
                        ConditionalGet(f"{base_url}/start/child", etag='"known"'),
                    ),
                )
            )
        ]

    assert set(requested) == {"/start", "/start/child"}
    assert len([event for event in events if isinstance(event, PageUnchanged)]) == 2
    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=0,
        pages_failed=0,
        pages_unchanged=2,
    )


async def test_truncated_conditional_frontier_marks_link_crawl_partial() -> None:
    async def page(_: web.Request) -> web.Response:
        return web.Response(text="<main>Known page</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    download_files=False,
                    conditional_gets_truncated=True,
                )
            )
        ]

    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=1,
        pages_failed=0,
        reason="item_limit",
    )


async def test_engine_marks_excess_conditional_hints_as_partial() -> None:
    requested: list[str] = []

    async def not_modified(request: web.Request) -> web.Response:
        requested.append(request.path)
        return web.Response(status=304)

    app = web.Application()
    app.router.add_get("/start", not_modified)
    app.router.add_get("/start/child", not_modified)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    download_files=False,
                    max_items=1,
                    conditional_gets=(
                        ConditionalGet(f"{base_url}/start", etag='"known"'),
                        ConditionalGet(f"{base_url}/start/child", etag='"known"'),
                    ),
                )
            )
        ]

    assert requested == ["/start"]
    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=0,
        pages_failed=0,
        pages_unchanged=1,
        reason="item_limit",
    )


async def test_crawl_retries_service_unavailable_with_retry_after() -> None:
    attempts = 0

    async def sometimes_unavailable(_: web.Request) -> web.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return web.Response(status=503, headers={"Retry-After": "0"})
        return web.Response(
            text="<main><h1>Tillgänglig igen</h1></main>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/start", sometimes_unavailable)
    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start")
            )
        ]

    assert attempts == 2
    assert any(
        isinstance(event, PageCrawled) and "Tillgänglig igen" in event.content
        for event in events
    )


async def test_sitemap_fetch_retries_service_unavailable() -> None:
    sitemap_attempts = 0

    async def sitemap(request: web.Request) -> web.Response:
        nonlocal sitemap_attempts
        sitemap_attempts += 1
        if sitemap_attempts == 1:
            return web.Response(status=503, headers={"Retry-After": "0"})
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{origin}/page</loc></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def page(_: web.Request) -> web.Response:
        return web.Response(text="<main>available</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/page", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    assert sitemap_attempts == 2
    assert any(isinstance(event, PageCrawled) for event in events)


async def test_empty_sitemap_emits_an_authoritative_snapshot() -> None:
    async def sitemap(_: web.Request) -> web.Response:
        return web.Response(
            body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" />',
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=0,
        pages_failed=0,
        sitemap_fingerprint=hashlib.sha256(b"").hexdigest(),
        sitemap_entries=0,
    )


async def test_discarded_validator_hints_do_not_make_empty_sitemap_partial() -> None:
    async def sitemap(_: web.Request) -> web.Response:
        return web.Response(
            body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" />',
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/sitemap.xml",
                    crawl_type=CrawlType.SITEMAP,
                    max_items=1,
                    conditional_gets=(
                        ConditionalGet(f"{base_url}/old-1", etag='"old"'),
                        ConditionalGet(f"{base_url}/old-2", etag='"old"'),
                    ),
                    conditional_gets_truncated=True,
                )
            )
        ]

    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=0,
        pages_failed=0,
        sitemap_fingerprint=hashlib.sha256(b"").hexdigest(),
        sitemap_entries=0,
    )


@pytest.mark.parametrize(
    "location",
    [
        "https://other.example.com/page",
        "mailto:contact@example.com",
        "{origin}/guide.pdf",
    ],
    ids=("off-origin", "unnormalizable", "non-page"),
)
async def test_filtered_only_sitemap_is_not_authoritatively_empty(
    location: str,
) -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{location.format(origin=origin)}</loc></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.sitemap_fingerprint is None


async def test_off_origin_only_sitemap_index_is_not_authoritatively_empty() -> None:
    async def sitemap(_: web.Request) -> web.Response:
        return web.Response(
            body=(
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<sitemap><loc>https://other.example.com/sitemap.xml</loc></sitemap>"
                "</sitemapindex>"
            ),
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.sitemap_fingerprint is None


@pytest.mark.parametrize(
    "body",
    [
        b"<urlset><foo><loc>https://example.com/page</loc></foo></urlset>",
        b"<urlset>upstream error</urlset>",
        b'<x:urlset xmlns:x="urn:not-sitemaps" />',
    ],
    ids=("unexpected-child", "root-text", "wrong-namespace"),
)
async def test_structurally_untrusted_sitemap_is_not_authoritatively_empty(
    body: bytes,
) -> None:
    async def sitemap(_: web.Request) -> web.Response:
        return web.Response(body=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.sitemap_fingerprint is None


async def test_sitemap_index_with_empty_child_is_authoritatively_empty() -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<sitemap><loc>{origin}/empty.xml</loc></sitemap>"
                "</sitemapindex>"
            ),
            content_type="application/xml",
        )

    async def empty(_: web.Request) -> web.Response:
        return web.Response(body=b"<urlset />", content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/empty.xml", empty)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.sitemap_fingerprint == hashlib.sha256(b"").hexdigest()


async def test_sitemap_index_with_discarded_item_content_is_not_empty() -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                "<sitemapindex><sitemap>"
                f"<loc>{origin}/empty.xml</loc>"
                "<unexpected>"
                f"<loc>{origin}/populated.xml</loc>"
                "</unexpected>"
                "</sitemap></sitemapindex>"
            ),
            content_type="application/xml",
        )

    async def empty(_: web.Request) -> web.Response:
        return web.Response(body=b"<urlset />", content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/empty.xml", empty)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.sitemap_fingerprint is None


async def test_sitemap_with_visible_page_and_discarded_content_is_incomplete() -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                "<urlset><url>"
                f"<loc>{origin}/visible</loc>"
                "<lastmod>2026-09-02</lastmod>"
                "<unexpected>"
                f"<loc>{origin}/hidden</loc>"
                "</unexpected>"
                "</url></urlset>"
            ),
            content_type="application/xml",
        )

    async def visible(_: web.Request) -> web.Response:
        return web.Response(text="<main>Visible</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/visible", visible)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    assert any(
        isinstance(event, PageFailed) and event.reason == "invalid_sitemap"
        for event in events
    )
    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.pages_crawled == 1
    assert finished.pages_failed == 1
    assert finished.sitemap_fingerprint is None


async def test_sitemap_skips_missing_location_without_losing_valid_pages() -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                "<urlset>"
                "<url><loc> </loc></url>"
                f"<url><loc>{origin}/one</loc><lastmod>2026-09-01</lastmod></url>"
                f"<url><loc>{origin}/two</loc><lastmod>2026-09-02</lastmod></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def page(_: web.Request) -> web.Response:
        return web.Response(text="<main>Visible</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/one", page)
    app.router.add_get("/two", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    assert (
        sum(
            isinstance(event, PageFailed) and event.reason == "invalid_sitemap"
            for event in events
        )
        == 1
    )
    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.pages_crawled == 2
    assert finished.pages_failed == 1
    assert finished.sitemap_fingerprint is None


async def test_crawl_rejects_oversized_response() -> None:
    async def oversized(_: web.Request) -> web.Response:
        return web.Response(text="<main>too large</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", oversized)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", max_response_bytes=10)
            )
        ]

    assert events[0] == PageFailed(url=f"{base_url}/start", reason="response_too_large")


async def test_crawl_with_no_file_links_skips_temporary_directory(
    monkeypatch,
) -> None:
    def unexpected_temporary_directory(*args, **kwargs):
        del args, kwargs
        raise AssertionError("crawl allocated a file directory")

    monkeypatch.setattr(
        "eneo.crawler.python_engine.TemporaryDirectory",
        unexpected_temporary_directory,
    )

    async def start(_: web.Request) -> web.Response:
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", download_files=True)
            )
        ]

    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=1,
        pages_failed=0,
    )


def test_download_filenames_preserve_unicode_and_fit_filesystem_limits() -> None:
    arabic = PythonCrawlEngine._filename_for_url(
        f"https://example.se/files/{quote('دليل البلدية.pdf')}", set()
    )
    long_arabic = PythonCrawlEngine._filename_for_url(
        f"https://example.se/files/{quote('م' * 300 + '.pdf')}", set()
    )
    extreme_suffix = PythonCrawlEngine._filename_for_url(
        f"https://example.se/files/{quote('report.' + 'x' * 300)}", set()
    )
    nfd_source = "Cafe\u0301.pdf"
    nfd = PythonCrawlEngine._filename_for_url(
        f"https://example.se/files/{quote(nfd_source)}", set()
    )

    colliding_url = "https://example.se/other/report.pdf?version=2"
    collision_digest = hashlib.sha256(colliding_url.encode()).hexdigest()[:8]
    taken_names = {"report.pdf", f"report_{collision_digest}.pdf"}
    collision = PythonCrawlEngine._filename_for_url(colliding_url, taken_names)
    partial_collision = PythonCrawlEngine._filename_for_url(
        "https://example.se/files/report.pdf",
        {"report.pdf.part"},
    )

    long_names: set[str] = set()
    long_url = f"https://example.se/files/{quote('م' * 300 + '.pdf')}"
    first_long = PythonCrawlEngine._filename_for_url(long_url, long_names)
    second_long = PythonCrawlEngine._filename_for_url(
        f"{long_url}?version=2", long_names
    )

    assert arabic == "دليل_البلدية.pdf"
    assert long_arabic.endswith(".pdf")
    assert extreme_suffix.startswith("report")
    assert nfd == "Café.pdf"
    assert collision not in {"report.pdf", f"report_{collision_digest}.pdf"}
    assert partial_collision != "report.pdf"
    assert len({first_long, second_long}) == 2
    assert all(
        len(name.encode("utf-8")) <= 200
        for name in (
            arabic,
            long_arabic,
            extreme_suffix,
            nfd,
            collision,
            first_long,
            second_long,
        )
    )


def test_orphan_cleanup_only_removes_crawler_owned_directories(
    tmp_path: Path,
) -> None:
    orphan = tmp_path / "eneo-crawl-abandoned"
    orphan.mkdir()
    (orphan / "download.pdf").write_bytes(b"document bytes")

    upload_staging = tmp_path / "job-staging"
    upload_staging.mkdir()
    exports = tmp_path / "exports"
    exports.mkdir()
    legacy_file = tmp_path / "tmp12345678"
    legacy_file.write_text("legacy crawl or unrelated temporary file")
    prefixed_file = tmp_path / "eneo-crawl-not-a-directory"
    prefixed_file.write_text("not owned by TemporaryDirectory")
    prefixed_symlink = tmp_path / "eneo-crawl-not-owned"
    prefixed_symlink.symlink_to(upload_staging, target_is_directory=True)

    removed = python_engine.cleanup_orphaned_crawl_directories(tmp_path)

    assert removed == 1
    assert not orphan.exists()
    assert upload_staging.is_dir()
    assert exports.is_dir()
    assert legacy_file.is_file()
    assert prefixed_file.is_file()
    assert prefixed_symlink.is_symlink()


def test_orphan_cleanup_continues_after_one_workspace_cannot_be_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = tmp_path / "eneo-crawl-blocked"
    blocked.mkdir()
    recoverable = tmp_path / "eneo-crawl-recoverable"
    recoverable.mkdir()
    remove_tree = python_engine.shutil.rmtree

    def fail_for_blocked_workspace(path: Path) -> None:
        if path == blocked:
            raise PermissionError("workspace is not writable")
        remove_tree(path)

    monkeypatch.setattr(python_engine.shutil, "rmtree", fail_for_blocked_workspace)

    removed = python_engine.cleanup_orphaned_crawl_directories(tmp_path)

    assert removed == 1
    assert blocked.is_dir()
    assert not recoverable.exists()


async def test_downloaded_file_is_removed_after_event_consumer_resumes() -> None:
    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text=(
                '<main><a href="/first.pdf">First</a>'
                '<a href="/second.pdf">Second</a></main>'
            ),
            content_type="text/html",
        )

    async def file_response(_: web.Request) -> web.Response:
        return web.Response(body=b"document bytes", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/first.pdf", file_response)
    app.router.add_get("/second.pdf", file_response)

    async with _serve(app) as base_url:
        downloaded_paths: list[Path] = []
        async for event in PythonCrawlEngine(allow_private_network=True).crawl(
            _request(f"{base_url}/start")
        ):
            if isinstance(event, FileDownloaded):
                assert event.path.read_bytes() == b"document bytes"
                if downloaded_paths:
                    assert not downloaded_paths[-1].exists()
                downloaded_paths.append(event.path)

    assert len(downloaded_paths) == 2
    assert all(not path.exists() for path in downloaded_paths)


async def test_file_download_retries_service_unavailable() -> None:
    file_attempts = 0

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/guide.pdf">Guide</a></main>',
            content_type="text/html",
        )

    async def guide(_: web.Request) -> web.Response:
        nonlocal file_attempts
        file_attempts += 1
        if file_attempts == 1:
            return web.Response(status=503, headers={"Retry-After": "0"})
        return web.Response(body=b"document bytes", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/guide.pdf", guide)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start")
            )
        ]

    assert file_attempts == 2
    assert any(isinstance(event, FileDownloaded) for event in events)
    assert not any(isinstance(event, FileFailed) for event in events)


async def test_file_download_retries_an_incomplete_payload_from_a_clean_file() -> None:
    file_attempts = 0

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/guide.pdf">Guide</a></main>',
            content_type="text/html",
        )

    async def guide(request: web.Request) -> web.StreamResponse:
        nonlocal file_attempts
        file_attempts += 1
        if file_attempts == 1:
            response = web.StreamResponse(
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Length": "32",
                }
            )
            await response.prepare(request)
            await response.write(b"incomplete")
            assert request.transport is not None
            request.transport.close()
            return response
        return web.Response(body=b"complete document", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/guide.pdf", guide)

    async with _serve(app) as base_url:
        downloaded: list[bytes] = []
        async for event in PythonCrawlEngine(allow_private_network=True).crawl(
            _request(f"{base_url}/start")
        ):
            if isinstance(event, FileDownloaded):
                downloaded.append(event.path.read_bytes())

    assert file_attempts == 2
    assert downloaded == [b"complete document"]


async def test_retry_backoff_releases_process_wide_http_capacity(monkeypatch) -> None:
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity", None)
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity_loop", None)
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity_limit", None)
    first_attempt_finished = asyncio.Event()
    other_request_started = asyncio.Event()
    flaky_attempts = 0

    async def flaky(_: web.Request) -> web.Response:
        nonlocal flaky_attempts
        flaky_attempts += 1
        if flaky_attempts == 1:
            first_attempt_finished.set()
            return web.Response(status=503, headers={"Retry-After": "30"})
        return web.Response(text="<main>recovered</main>", content_type="text/html")

    async def other(_: web.Request) -> web.Response:
        other_request_started.set()
        return web.Response(text="<main>other</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/flaky", flaky)
    app.router.add_get("/other", other)

    async with _serve(app) as base_url:
        engine = PythonCrawlEngine(global_concurrency=1, allow_private_network=True)

        async def collect(path: str) -> list[CrawlEvent]:
            return [
                event
                async for event in engine.crawl(
                    _request(f"{base_url}/{path}", download_files=False)
                )
            ]

        flaky_task = asyncio.create_task(collect("flaky"))
        other_task: asyncio.Task[list[CrawlEvent]] | None = None
        try:
            await asyncio.wait_for(first_attempt_finished.wait(), timeout=2)
            other_task = asyncio.create_task(collect("other"))
            await asyncio.wait_for(other_request_started.wait(), timeout=2)
            await other_task
        finally:
            flaky_task.cancel()
            if other_task is not None and not other_task.done():
                other_task.cancel()
            await asyncio.gather(
                flaky_task,
                *([other_task] if other_task is not None else []),
                return_exceptions=True,
            )

    assert flaky_attempts == 1


async def test_closing_crawl_stream_removes_download_workspace() -> None:
    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/guide.pdf">Guide</a></main>',
            content_type="text/html",
        )

    async def guide(_: web.Request) -> web.Response:
        return web.Response(body=b"document bytes", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/guide.pdf", guide)

    async with _serve(app) as base_url:
        stream = PythonCrawlEngine(allow_private_network=True).crawl(
            _request(f"{base_url}/start")
        )
        downloaded_path: Path | None = None
        async for event in stream:
            if isinstance(event, FileDownloaded):
                downloaded_path = event.path
                break

        assert downloaded_path is not None
        workspace = downloaded_path.parent
        assert downloaded_path.is_file()
        await stream.aclose()
        assert not workspace.exists()


async def test_file_size_limit_applies_to_streams_without_content_length(
    monkeypatch,
    tmp_path,
) -> None:
    download_directory = tmp_path / "downloads"
    download_directory.mkdir()

    class PersistentTemporaryDirectory:
        name = str(download_directory)

        @staticmethod
        def cleanup() -> None:
            pass

    monkeypatch.setattr(
        "eneo.crawler.python_engine.TemporaryDirectory",
        lambda *args, **kwargs: PersistentTemporaryDirectory(),
    )

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/large.pdf">Large file</a></main>',
            content_type="text/html",
        )

    async def large(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "application/pdf"})
        await response.prepare(request)
        await response.write(b"1234")
        await response.write(b"5678")
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/large.pdf", large)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", max_file_bytes=5)
            )
        ]

    assert any(
        isinstance(event, FileFailed) and event.reason == "file_too_large"
        for event in events
    )
    assert not any(isinstance(event, FileDownloaded) for event in events)
    assert list(download_directory.iterdir()) == []
    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=1,
        pages_failed=0,
        files_failed=1,
    )


async def test_file_downloads_use_bounded_concurrency() -> None:
    active = 0
    peak = 0

    async def start(_: web.Request) -> web.Response:
        links = "".join(
            f'<a href="/file-{index}.pdf">File {index}</a>' for index in range(4)
        )
        return web.Response(text=f"<main>{links}</main>", content_type="text/html")

    async def download(request: web.Request) -> web.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
            return web.Response(
                body=request.path.encode(), content_type="application/pdf"
            )
        finally:
            active -= 1

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/file-{index}.pdf", download)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", concurrency=2)
            )
        ]

    downloads = [event for event in events if isinstance(event, FileDownloaded)]
    assert len(downloads) == 4
    assert peak == 2
    assert events[-1] == CrawlFinished(
        status="completed",
        pages_crawled=1,
        pages_failed=0,
        files_downloaded=4,
    )


async def test_file_downloads_are_emitted_in_completion_order() -> None:
    both_started = asyncio.Event()
    started = 0

    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text=(
                '<main><a href="/a-slow.pdf">Slow</a>'
                '<a href="/b-fast.pdf">Fast</a></main>'
            ),
            content_type="text/html",
        )

    async def download(request: web.Request) -> web.Response:
        nonlocal started
        started += 1
        if started == 2:
            both_started.set()
        await both_started.wait()
        if request.path == "/a-slow.pdf":
            await asyncio.sleep(0.05)
        return web.Response(body=b"file", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/a-slow.pdf", download)
    app.router.add_get("/b-fast.pdf", download)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", concurrency=2)
            )
        ]

    downloads = [event for event in events if isinstance(event, FileDownloaded)]
    assert [event.url for event in downloads] == [
        f"{base_url}/b-fast.pdf",
        f"{base_url}/a-slow.pdf",
    ]


async def test_process_wide_http_capacity_bounds_concurrent_crawls(monkeypatch) -> None:
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity", None)
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity_loop", None)
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity_limit", None)
    active = 0
    peak = 0

    async def slow(_: web.Request) -> web.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
            return web.Response(text="<main>ok</main>", content_type="text/html")
        finally:
            active -= 1

    app = web.Application()
    app.router.add_get("/one", slow)
    app.router.add_get("/two", slow)

    async with _serve(app) as base_url:
        first_engine = PythonCrawlEngine(
            global_concurrency=1, allow_private_network=True
        )
        second_engine = PythonCrawlEngine(
            global_concurrency=1, allow_private_network=True
        )

        async def collect(engine: PythonCrawlEngine, path: str) -> list[CrawlEvent]:
            return [
                event async for event in engine.crawl(_request(f"{base_url}/{path}"))
            ]

        await asyncio.gather(
            collect(first_engine, "one"), collect(second_engine, "two")
        )

    assert peak == 1


async def test_waiting_crawl_gets_next_global_slot_when_twenty_are_busy(
    monkeypatch,
) -> None:
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity", None)
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity_loop", None)
    monkeypatch.setattr("eneo.crawler.python_engine._process_capacity_limit", None)
    all_slow_slots_started = asyncio.Event()
    release_slow_slot = asyncio.Semaphore(0)
    fast_started = asyncio.Event()
    slow_refilled_before_fast = False
    active_slow_children = 0

    async def slow_seed(request: web.Request) -> web.Response:
        crawl = request.match_info["crawl"]
        links = "".join(
            f'<a href="/slow/{crawl}/child-{index}">child</a>' for index in range(5)
        )
        return web.Response(
            text=f"<main>{links}</main>",
            content_type="text/html",
        )

    async def slow_child(request: web.Request) -> web.Response:
        nonlocal active_slow_children, slow_refilled_before_fast
        if request.match_info["child"] == "4" and not fast_started.is_set():
            slow_refilled_before_fast = True
        active_slow_children += 1
        if active_slow_children == 20:
            all_slow_slots_started.set()
        try:
            await release_slow_slot.acquire()
            return web.Response(
                text="<main>slow child</main>", content_type="text/html"
            )
        finally:
            active_slow_children -= 1

    async def fast(_: web.Request) -> web.Response:
        fast_started.set()
        return web.Response(text="<main>fast</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/slow/{crawl}", slow_seed)
    app.router.add_get("/slow/{crawl}/child-{child}", slow_child)
    app.router.add_get("/fast", fast)

    async with _serve(app) as base_url:
        engine = PythonCrawlEngine(global_concurrency=20, allow_private_network=True)

        async def collect(path: str) -> list[CrawlEvent]:
            return [
                event
                async for event in engine.crawl(
                    _request(
                        f"{base_url}/{path}",
                        max_items=6,
                        concurrency=4,
                        download_files=False,
                    )
                )
            ]

        slow_tasks = [
            asyncio.create_task(collect(f"slow/{index}")) for index in range(5)
        ]
        await asyncio.wait_for(all_slow_slots_started.wait(), timeout=1)
        fast_task = asyncio.create_task(collect("fast"))
        await asyncio.sleep(0.02)
        release_slow_slot.release()
        await asyncio.wait_for(fast_started.wait(), timeout=1)
        for _ in range(24):
            release_slow_slot.release()
        await asyncio.wait_for(asyncio.gather(*slow_tasks, fast_task), timeout=1)

    assert fast_started.is_set()
    assert not slow_refilled_before_fast


async def test_sitemap_lastmod_emits_stable_snapshot() -> None:
    async def sitemap(request: web.Request) -> web.Response:
        origin = f"{request.scheme}://{request.host}"
        return web.Response(
            body=(
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{origin}/page</loc><lastmod>2026-08-01</lastmod></url>"
                "</urlset>"
            ),
            content_type="application/xml",
        )

    async def page(_: web.Request) -> web.Response:
        return web.Response(text="<main>ok</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    app.router.add_get("/page", page)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.sitemap_entries == 1
    assert finished.sitemap_fingerprint is not None


def test_non_global_network_targets_are_rejected() -> None:
    assert not _address_is_allowed("127.0.0.1", allow_private_network=False)
    assert not _address_is_allowed("169.254.169.254", allow_private_network=False)
    assert not _address_is_allowed("10.0.0.1", allow_private_network=False)
    assert not _address_is_allowed("224.0.0.1", allow_private_network=False)
    assert not _address_is_allowed("::1", allow_private_network=False)
    assert _address_is_allowed("8.8.8.8", allow_private_network=False)
    with pytest.raises(_UnsafeTarget):
        _reject_disallowed_literal(
            "http://169.254.169.254/latest/meta-data/",
            allow_private_network=False,
        )


async def test_private_seed_becomes_a_safe_page_failure() -> None:
    events = [
        event
        async for event in PythonCrawlEngine().crawl(
            _request("http://127.0.0.1:9/private")
        )
    ]

    assert isinstance(events[0], PageFailed)
    assert events[0].reason == "unsafe_target"


async def test_redirect_is_validated_before_out_of_scope_target_is_requested() -> None:
    target_requested = False

    async def redirect(_: web.Request) -> web.Response:
        return web.Response(status=302, headers={"Location": "http://169.254.169.254/"})

    async def target(_: web.Request) -> web.Response:
        nonlocal target_requested
        target_requested = True
        return web.Response(text="never", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", redirect)
    app.router.add_get("/target", target)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start")
            )
        ]

    assert not target_requested
    assert isinstance(events[0], PageFailed)
    assert events[0].reason == "redirect_rejected"


async def test_basic_auth_is_not_sent_after_origin_change() -> None:
    seen_authorization: list[str | None] = []

    async def attacker(request: web.Request) -> web.Response:
        seen_authorization.append(request.headers.get("Authorization"))
        return web.Response(text="never", content_type="text/html")

    attacker_app = web.Application()
    attacker_app.router.add_get("/target", attacker)
    async with _serve(attacker_app) as attacker_url:

        async def redirect(_: web.Request) -> web.Response:
            return web.Response(
                status=302, headers={"Location": f"{attacker_url}/target"}
            )

        origin_app = web.Application()
        origin_app.router.add_get("/start", redirect)
        async with _serve(origin_app) as base_url:
            request = _request(f"{base_url}/start")
            request = CrawlRequest(
                url=request.url,
                crawl_type=request.crawl_type,
                download_files=request.download_files,
                obey_robots=request.obey_robots,
                limits=request.limits,
                http_user="user",
                http_pass="secret",
            )
            engine = PythonCrawlEngine(allow_private_network=True)
            events = [event async for event in engine.crawl(request)]

    assert seen_authorization == []
    assert isinstance(events[0], PageFailed)
    assert events[0].reason == "redirect_rejected"


async def test_page_limit_marks_crawl_partial() -> None:
    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/start/child">child</a></main>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/start", start)
    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", max_items=1)
            )
        ]

    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=1,
        pages_failed=0,
        reason="item_limit",
    )


async def test_max_seconds_marks_slow_crawl_partial() -> None:
    async def slow(_: web.Request) -> web.Response:
        await asyncio.sleep(0.1)
        return web.Response(text="<main>late</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", slow)
    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", max_seconds=0.01)
            )
        ]

    assert events == [
        CrawlFinished(
            status="partial",
            pages_crawled=0,
            pages_failed=0,
            reason="timeout",
        )
    ]


async def test_max_seconds_includes_robots_fetch() -> None:
    async def slow_robots(_: web.Request) -> web.Response:
        await asyncio.sleep(0.1)
        return web.Response(text="User-agent: *", content_type="text/plain")

    app = web.Application()
    app.router.add_get("/robots.txt", slow_robots)
    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(
                    f"{base_url}/start",
                    obey_robots=True,
                    max_seconds=0.01,
                )
            )
        ]

    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=0,
        pages_failed=0,
        reason="timeout",
    )


async def test_file_downloads_share_the_overall_crawl_deadline() -> None:
    async def start(_: web.Request) -> web.Response:
        return web.Response(
            text='<main><a href="/slow.pdf">file</a></main>',
            content_type="text/html",
        )

    async def slow_file(_: web.Request) -> web.Response:
        await asyncio.sleep(0.2)
        return web.Response(body=b"late", content_type="application/pdf")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/slow.pdf", slow_file)
    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start", max_seconds=0.05)
            )
        ]

    finished = events[-1]
    assert isinstance(finished, CrawlFinished)
    assert finished.status == "partial"
    assert finished.reason == "timeout"
    assert not any(isinstance(event, FileDownloaded) for event in events)


async def test_bogus_response_charset_becomes_page_failure() -> None:
    async def bogus(_: web.Request) -> web.Response:
        return web.Response(
            body=b"<main>content</main>",
            headers={"Content-Type": "text/html; charset=not-a-real-charset"},
        )

    app = web.Application()
    app.router.add_get("/start", bogus)
    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                _request(f"{base_url}/start")
            )
        ]

    assert isinstance(events[0], PageFailed)
    assert events[0].reason == "response_decode_error"


async def test_cancellation_propagates_and_stops_in_flight_fetches() -> None:
    request_started = asyncio.Event()
    release_request = asyncio.Event()

    async def blocked(_: web.Request) -> web.Response:
        request_started.set()
        await release_request.wait()
        return web.Response(text="released", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", blocked)
    async with _serve(app) as base_url:

        async def collect() -> list[CrawlEvent]:
            return [
                event
                async for event in PythonCrawlEngine(allow_private_network=True).crawl(
                    _request(f"{base_url}/start")
                )
            ]

        crawl_task = asyncio.create_task(collect())
        await asyncio.wait_for(request_started.wait(), timeout=1)
        crawl_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await crawl_task
        release_request.set()


def test_crawl_request_repr_redacts_password() -> None:
    request = _request("https://example.se/")
    authenticated = CrawlRequest(
        url=request.url,
        crawl_type=request.crawl_type,
        download_files=request.download_files,
        obey_robots=request.obey_robots,
        limits=request.limits,
        http_user="admin",
        http_pass="top-secret",
    )

    assert "top-secret" not in repr(authenticated)
