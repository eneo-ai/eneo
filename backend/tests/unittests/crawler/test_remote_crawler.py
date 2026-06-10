"""Unit tests for RemoteCrawler (external crawler service client).

RemoteCrawler must be a drop-in for the in-process Crawler: same crawl()
context manager, same Crawl result shape, same partial-salvage semantics.
Tests drive it against a local aiohttp test server emitting NDJSON events.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from intric.crawler.remote_crawler import (
    RemoteCrawler,
    _filename_for_link,
    create_crawler,
)
from intric.main.exceptions import CrawlerException, CrawlTimeoutError
from intric.websites.domain.crawl_run import CrawlType


def ndjson(*events: dict) -> bytes:
    return b"".join(json.dumps(e).encode() + b"\n" for e in events)


class ServiceStub:
    """Configurable /v1/crawls handler capturing the request it received."""

    def __init__(self):
        self.body: bytes = b""
        self.status: int = 200
        self.received_json: dict | None = None
        self.received_headers: dict | None = None
        self.abort_after_write: bool = False

    async def handle(self, request: web.Request) -> web.StreamResponse:
        self.received_json = await request.json()
        self.received_headers = dict(request.headers)
        if self.status != 200:
            return web.Response(status=self.status, text="nope")
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "application/x-ndjson"}
        )
        await response.prepare(request)
        await response.write(self.body)
        if self.abort_after_write:
            assert request.transport is not None
            request.transport.close()
            return response
        await response.write_eof()
        return response


@pytest.fixture
async def service():
    stub = ServiceStub()
    app = web.Application()
    app.router.add_post("/v1/crawls", stub.handle)

    async def serve_file(request: web.Request) -> web.Response:
        size = int(request.match_info["size"])
        return web.Response(body=b"x" * size, content_type="application/pdf")

    app.router.add_get("/files/{size}/{name}", serve_file)

    server = TestServer(app)
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    yield stub
    await server.close()


def page(url: str, title: str = "", content: str = "innehåll", **extra) -> dict:
    return {
        "type": "page",
        "url": url,
        "title": title or url,
        "content": content,
        **extra,
    }


DONE = {"type": "done", "outcome": {"ok_count": 0, "termination_reason": "completed"}}


class TestStreamHappyPath:
    @pytest.mark.asyncio
    async def test_pages_are_spooled_and_iterated(self, service):
        service.body = ndjson(
            page("https://k.se/a", "A"), page("https://k.se/b", "B"), DONE
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            pages = list(crawl.pages)

        assert crawl.pages_count == 2
        assert crawl.is_partial is False
        assert crawl.termination_reason == "completed"
        assert [(p.url, p.title, p.content) for p in pages] == [
            ("https://k.se/a", "A", "innehåll"),
            ("https://k.se/b", "B", "innehåll"),
        ]

    @pytest.mark.asyncio
    async def test_request_carries_settings_auth_and_crawl_type(self, service):
        service.body = ndjson(page("https://k.se/a"), DONE)
        crawler = RemoteCrawler(base_url=service.base_url, api_key="secret-key")

        async with crawler.crawl(
            url="https://k.se/sitemap.xml",
            crawl_type=CrawlType.SITEMAP,
            http_user="intern",
            http_pass="hemligt",
            tenant_crawler_settings={
                "closespider_itemcount": 500,
                "crawl_max_length": 3600,
            },
        ) as crawl:
            list(crawl.pages)

        body = service.received_json
        assert body["crawl_type"] == "sitemap"
        assert body["http_auth"] == {"username": "intern", "password": "hemligt"}
        assert body["limits"]["max_pages"] == 500
        assert body["limits"]["max_seconds"] == 3600
        assert body["delivery"] == {"mode": "stream"}
        assert service.received_headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.asyncio
    async def test_raw_text_field_and_missing_title_tolerated(self, service):
        service.body = ndjson(
            {"type": "page", "url": "https://k.se/x", "raw_text": "via raw_text"},
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            (p,) = list(crawl.pages)

        assert p.content == "via raw_text"
        assert p.title == "https://k.se/x"

    @pytest.mark.asyncio
    async def test_early_service_termination_marks_partial(self, service):
        service.body = ndjson(
            page("https://k.se/a"),
            {"type": "done", "outcome": {"termination_reason": "max_seconds"}},
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            list(crawl.pages)

        assert crawl.is_partial is True
        assert crawl.termination_reason == "max_seconds"

    @pytest.mark.asyncio
    async def test_heartbeat_callback_invoked(self, service):
        service.body = ndjson(page("https://k.se/a"), DONE)
        crawler = RemoteCrawler(base_url=service.base_url)
        beats = 0

        async def tick():
            nonlocal beats
            beats += 1

        async with crawler.crawl(
            url="https://k.se", heartbeat_callback=tick, heartbeat_interval=0.01
        ) as crawl:
            list(crawl.pages)

        assert beats >= 1


class TestFailureSemantics:
    @pytest.mark.asyncio
    async def test_non_200_raises_crawler_exception(self, service):
        service.status = 503
        crawler = RemoteCrawler(base_url=service.base_url)

        with pytest.raises(CrawlerException, match="503"):
            async with crawler.crawl(url="https://k.se"):
                pass

    @pytest.mark.asyncio
    async def test_zero_pages_raises(self, service):
        service.body = ndjson(DONE)
        crawler = RemoteCrawler(base_url=service.base_url)

        with pytest.raises(CrawlerException, match="returned no pages"):
            async with crawler.crawl(url="https://k.se"):
                pass

    @pytest.mark.asyncio
    async def test_mid_stream_disconnect_salvages_pages(self, service):
        service.body = ndjson(page("https://k.se/a"), page("https://k.se/b"))
        service.abort_after_write = True
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            pages = list(crawl.pages)

        assert len(pages) == 2
        assert crawl.is_partial is True
        assert crawl.termination_reason == "stream_interrupted"

    @pytest.mark.asyncio
    async def test_mid_stream_disconnect_without_pages_raises(self, service):
        service.body = b""
        service.abort_after_write = True
        crawler = RemoteCrawler(base_url=service.base_url)

        with pytest.raises(CrawlerException):
            async with crawler.crawl(url="https://k.se"):
                pass

    @pytest.mark.asyncio
    async def test_client_timeout_salvages_as_timeout(self, service):
        service.body = ndjson(page("https://k.se/a"))
        service.abort_after_write = True
        crawler = RemoteCrawler(base_url=service.base_url)

        # Force the client-side ceiling to fire instead of the disconnect
        with patch(
            "intric.crawler.remote_crawler.RemoteCrawler._stream_crawl",
            side_effect=asyncio.TimeoutError,
        ):
            with pytest.raises(CrawlTimeoutError):
                async with crawler.crawl(url="https://k.se"):
                    pass


class TestFileDownloads:
    @pytest.mark.asyncio
    async def test_file_links_downloaded_into_files_dir(self, service):
        file_url = f"{service.base_url}/files/64/rapport.pdf"
        service.body = ndjson(
            page(
                "https://k.se/a",
                file_links=[{"url": file_url, "mime": "application/pdf"}],
            ),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se", download_files=True) as crawl:
            list(crawl.pages)
            files = list(crawl.files)
            # Files live in the crawl's temp dir: read inside the context,
            # exactly like the worker's file-processing loop does
            assert [f.name for f in files] == ["rapport.pdf"]
            assert files[0].read_bytes() == b"x" * 64

    @pytest.mark.asyncio
    async def test_oversized_file_skipped(self, service):
        # download_max_size floor is 1 MiB; serve a file just above it
        file_url = f"{service.base_url}/files/{1048576 + 1024}/stor.pdf"
        service.body = ndjson(
            page("https://k.se/a", file_links=[file_url]),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(
            url="https://k.se",
            download_files=True,
            tenant_crawler_settings={"download_max_size": 1048576},
        ) as crawl:
            list(crawl.pages)
            files = list(crawl.files)

        assert files == []

    @pytest.mark.asyncio
    async def test_files_not_fetched_when_download_files_false(self, service):
        file_url = f"{service.base_url}/files/64/rapport.pdf"
        service.body = ndjson(page("https://k.se/a", file_links=[file_url]), DONE)
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se", download_files=False) as crawl:
            list(crawl.pages)
            files = list(crawl.files)

        assert files == []


class TestFilenameForLink:
    def test_sanitizes_and_dedupes(self):
        taken: set[str] = set()
        first = _filename_for_link("https://k.se/docs/r%20apport.pdf", taken, 0)
        second = _filename_for_link("https://k.se/other/r apport.pdf", taken, 1)
        assert first == "r_apport.pdf"
        assert second == "1_r_apport.pdf"

    def test_fallback_for_extensionless_root(self):
        assert _filename_for_link("https://k.se/", set(), 7) == "file-7"


class TestCreateCrawler:
    def test_returns_remote_when_url_configured(self):
        with patch(
            "intric.main.config.get_settings",
            return_value=SimpleNamespace(
                crawler_service_url="http://crawler:8870",
                crawler_service_api_key="k",
            ),
        ):
            crawler = create_crawler()
        assert isinstance(crawler, RemoteCrawler)
        assert crawler.base_url == "http://crawler:8870"

    def test_raises_clear_error_when_unset(self):
        with patch(
            "intric.main.config.get_settings",
            return_value=SimpleNamespace(
                crawler_service_url=None, crawler_service_api_key=None
            ),
        ):
            with pytest.raises(CrawlerException, match="CRAWLER_SERVICE_URL"):
                create_crawler()
