import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiohttp import web

from eneo.crawler.engine import (
    ConditionalGet,
    CrawlFinished,
    CrawlLimits,
    CrawlRequest,
    PageCrawled,
    PageFailed,
    PageUnchanged,
)
from eneo.crawler.python_engine import PythonCrawlEngine
from eneo.websites.domain.crawl_run import CrawlType


def _request(
    url: str,
    *,
    crawl_type: CrawlType = CrawlType.CRAWL,
    obey_robots: bool = False,
    max_response_bytes: int = 100_000,
    conditional_gets: tuple[ConditionalGet, ...] = (),
) -> CrawlRequest:
    return CrawlRequest(
        url=url,
        crawl_type=crawl_type,
        download_files=True,
        obey_robots=obey_robots,
        limits=CrawlLimits(
            max_pages=10,
            max_seconds=10,
            request_timeout_seconds=2,
            max_response_bytes=max_response_bytes,
            concurrency=2,
            retries=1,
        ),
        conditional_gets=conditional_gets,
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
            async for event in PythonCrawlEngine().crawl(_request(f"{base_url}/start"))
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
            async for event in PythonCrawlEngine().crawl(
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
            async for event in PythonCrawlEngine().crawl(
                _request(f"{base_url}/sitemap.xml", crawl_type=CrawlType.SITEMAP)
            )
        ]

    pages = [event for event in events if isinstance(event, PageCrawled)]
    assert [page.url for page in pages] == [f"{base_url}/page"]
    assert events[-1] == CrawlFinished(
        status="completed", pages_crawled=1, pages_failed=0
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
            async for event in PythonCrawlEngine().crawl(
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
            async for event in PythonCrawlEngine().crawl(_request(f"{base_url}/start"))
        ]

    assert attempts == 2
    assert any(
        isinstance(event, PageCrawled) and "Tillgänglig igen" in event.content
        for event in events
    )


async def test_crawl_rejects_oversized_response() -> None:
    async def oversized(_: web.Request) -> web.Response:
        return web.Response(text="<main>too large</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", oversized)

    async with _serve(app) as base_url:
        events = [
            event
            async for event in PythonCrawlEngine().crawl(
                _request(f"{base_url}/start", max_response_bytes=10)
            )
        ]

    assert events[0] == PageFailed(url=f"{base_url}/start", reason="response_too_large")
