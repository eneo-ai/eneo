import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from eneo.crawler.engine import (
    ConditionalGet,
    CrawlEvent,
    CrawlFinished,
    CrawlLimits,
    CrawlRequest,
    FileDownloaded,
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
    max_pages: int = 10,
    max_seconds: float = 10,
    download_files: bool = True,
    concurrency: int = 2,
    conditional_gets: tuple[ConditionalGet, ...] = (),
) -> CrawlRequest:
    return CrawlRequest(
        url=url,
        crawl_type=crawl_type,
        download_files=download_files,
        obey_robots=obey_robots,
        limits=CrawlLimits(
            max_pages=max_pages,
            max_seconds=max_seconds,
            request_timeout_seconds=2,
            max_response_bytes=max_response_bytes,
            concurrency=concurrency,
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


async def test_downloaded_file_exists_until_event_consumer_resumes() -> None:
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
        downloaded_path = None
        async for event in PythonCrawlEngine(allow_private_network=True).crawl(
            _request(f"{base_url}/start")
        ):
            if isinstance(event, FileDownloaded):
                downloaded_path = event.path
                assert event.path.read_bytes() == b"document bytes"

    assert downloaded_path is not None
    assert not downloaded_path.exists()


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
    assert events[0].reason == "_UnsafeTarget"


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
    assert events[0].reason == "_RedirectRejected"


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
    assert events[0].reason == "_RedirectRejected"


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
                _request(f"{base_url}/start", max_pages=1)
            )
        ]

    assert events[-1] == CrawlFinished(
        status="partial",
        pages_crawled=1,
        pages_failed=0,
        reason="page_limit",
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
    assert events[0].reason == "LookupError"


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
