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

from eneo.crawler.remote_crawler import (
    RemoteCrawler,
    _filename_for_link,
    create_crawler,
)
from eneo.main.exceptions import CrawlerException, CrawlTimeoutError
from eneo.websites.domain.crawl_run import CrawlType


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
        self.preview_response: dict = {}
        self.preview_status: int = 200
        self.preview_received_json: dict | None = None
        # (path, Authorization header) for every linked-file fetch served
        self.file_requests: list[tuple[str, str | None]] = []

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

    async def handle_preview(self, request: web.Request) -> web.Response:
        self.preview_received_json = await request.json()
        if self.preview_status != 200:
            return web.Response(status=self.preview_status, text="nope")
        return web.json_response(self.preview_response)


@pytest.fixture
async def service():
    stub = ServiceStub()
    app = web.Application()
    app.router.add_post("/v1/crawls", stub.handle)
    app.router.add_post("/v1/preview", stub.handle_preview)

    async def serve_file(request: web.Request) -> web.Response:
        stub.file_requests.append((request.path, request.headers.get("Authorization")))
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
        "page": {
            "url": url,
            "title": title or url,
            "raw_text": content,
            "file_links": [],
            **extra,
        },
    }


DONE = {"type": "done", "status": "completed", "outcome": {"ok_count": 0}}


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
        assert body["depth"] == 10
        assert body["http_auth"] == {"user": "intern", "password": "hemligt"}
        assert body["limits"]["max_pages"] == 500
        assert body["limits"]["max_seconds"] == 3600
        assert body["delivery"] == {"mode": "stream"}
        assert service.received_headers["Authorization"] == "Bearer secret-key"

    @pytest.mark.asyncio
    async def test_content_field_and_missing_title_tolerated(self, service):
        service.body = ndjson(
            {
                "type": "page",
                "page": {"url": "https://k.se/x", "content": "via content"},
            },
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            (p,) = list(crawl.pages)

        assert p.content == "via content"
        assert p.title == "https://k.se/x"

    @pytest.mark.asyncio
    async def test_service_cancelled_status_marks_partial_timeout(self, service):
        service.body = ndjson(
            page("https://k.se/a"),
            {"type": "done", "status": "cancelled", "outcome": {"ok_count": 1}},
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            list(crawl.pages)

        assert crawl.is_partial is True
        assert crawl.termination_reason == "timeout"

    @pytest.mark.asyncio
    async def test_service_failed_status_marks_partial_error(self, service):
        service.body = ndjson(
            page("https://k.se/a"),
            {"type": "done", "status": "failed", "outcome": None, "error": "boom"},
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            list(crawl.pages)

        assert crawl.is_partial is True
        assert crawl.termination_reason == "error"

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
            "eneo.crawler.remote_crawler.RemoteCrawler._stream_crawl",
            side_effect=asyncio.TimeoutError,
        ):
            with pytest.raises(CrawlTimeoutError):
                async with crawler.crawl(url="https://k.se"):
                    pass


class TestConditionalGets:
    @pytest.mark.asyncio
    async def test_hints_sent_and_validators_returned_on_pages(self, service):
        service.body = ndjson(
            page(
                "https://k.se/a",
                etag='W/"abc"',
                last_modified="Tue, 09 Jun 2026 10:00:00 GMT",
            ),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)
        hints = [
            {
                "url": "https://k.se/a",
                "etag": 'W/"old"',
                "last_modified": None,
            }
        ]

        async with crawler.crawl(url="https://k.se", conditional_gets=hints) as crawl:
            pages = list(crawl.pages)

        assert service.received_json["conditional_gets"] == hints
        assert pages[0].etag == 'W/"abc"'
        assert pages[0].last_modified == "Tue, 09 Jun 2026 10:00:00 GMT"

    @pytest.mark.asyncio
    async def test_no_hints_omits_conditional_gets_from_request(self, service):
        service.body = ndjson(page("https://k.se/a"), DONE)
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            list(crawl.pages)

        assert "conditional_gets" not in service.received_json

    @pytest.mark.asyncio
    async def test_unchanged_events_collected(self, service):
        service.body = ndjson(
            {"type": "unchanged", "url": "https://k.se/a"},
            page("https://k.se/b"),
            {"type": "unchanged", "url": "https://k.se/c"},
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            pages = list(crawl.pages)

        assert crawl.unchanged_urls == ["https://k.se/a", "https://k.se/c"]
        assert [p.url for p in pages] == ["https://k.se/b"]

    @pytest.mark.asyncio
    async def test_all_unchanged_crawl_is_success_not_zero_pages(self, service):
        service.body = ndjson(
            {"type": "unchanged", "url": "https://k.se/a"},
            {"type": "unchanged", "url": "https://k.se/b"},
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            pages = list(crawl.pages)

        assert pages == []
        assert crawl.pages_count == 0
        assert crawl.unchanged_urls == ["https://k.se/a", "https://k.se/b"]
        assert crawl.is_partial is False

    @pytest.mark.asyncio
    async def test_disconnect_with_only_unchanged_salvages(self, service):
        service.body = ndjson({"type": "unchanged", "url": "https://k.se/a"})
        service.abort_after_write = True
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url="https://k.se") as crawl:
            pass

        assert crawl.unchanged_urls == ["https://k.se/a"]
        assert crawl.is_partial is True
        assert crawl.termination_reason == "stream_interrupted"


class TestFileDownloads:
    # The local test server is both the (mock) crawler service and the file
    # host, so the crawl seed is its base_url: linked files then live on the
    # crawl host, the realistic shape the worker downloads directly.
    @pytest.mark.asyncio
    async def test_file_links_downloaded_into_files_dir(self, service):
        file_url = f"{service.base_url}/files/64/rapport.pdf"
        service.body = ndjson(
            page(
                f"{service.base_url}/a",
                file_links=[{"url": file_url, "mime": "application/pdf"}],
            ),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url=service.base_url, download_files=True) as crawl:
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
            page(f"{service.base_url}/a", file_links=[file_url]),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(
            url=service.base_url,
            download_files=True,
            tenant_crawler_settings={"download_max_size": 1048576},
        ) as crawl:
            list(crawl.pages)
            files = list(crawl.files)

        assert files == []

    @pytest.mark.asyncio
    async def test_files_not_fetched_when_download_files_false(self, service):
        file_url = f"{service.base_url}/files/64/rapport.pdf"
        service.body = ndjson(
            page(f"{service.base_url}/a", file_links=[file_url]), DONE
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url=service.base_url, download_files=False) as crawl:
            list(crawl.pages)
            files = list(crawl.files)

        assert files == []

    @pytest.mark.asyncio
    async def test_same_host_download_carries_basic_auth(self, service):
        # Credentials are domain-locked: an on-host file fetch gets the auth
        file_url = f"{service.base_url}/files/64/rapport.pdf"
        service.body = ndjson(
            page(f"{service.base_url}/a", file_links=[file_url]), DONE
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(
            url=service.base_url,
            download_files=True,
            http_user="intern",
            http_pass="hemligt",
        ) as crawl:
            list(crawl.pages)
            assert [f.name for f in crawl.files] == ["rapport.pdf"]

        assert len(service.file_requests) == 1
        _, auth_header = service.file_requests[0]
        assert auth_header is not None and auth_header.startswith("Basic ")

    @pytest.mark.asyncio
    async def test_off_host_file_link_is_skipped_and_uncredentialed(self, service):
        # A page on the crawl host links a file on another host. The
        # domain-locked credentials must not follow it, and the off-host URL
        # must not be fetched at all.
        on_host = f"{service.base_url}/files/64/local.pdf"
        off_host = "http://other.host.invalid/files/64/leak.pdf"
        service.body = ndjson(
            page(f"{service.base_url}/a", file_links=[off_host, on_host]),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(
            url=service.base_url,
            download_files=True,
            http_user="intern",
            http_pass="hemligt",
        ) as crawl:
            list(crawl.pages)
            # Only the on-host file is downloaded; the off-host link is skipped
            assert [f.name for f in crawl.files] == ["local.pdf"]

        # The off-host host was never contacted (it is unresolvable on purpose);
        # only the single on-host request was served
        assert [req[0] for req in service.file_requests] == ["/files/64/local.pdf"]

    @pytest.mark.asyncio
    async def test_non_http_file_link_is_skipped(self, service):
        service.body = ndjson(
            page(
                f"{service.base_url}/a",
                file_links=["file:///etc/passwd", "ftp://k.se/secret"],
            ),
            DONE,
        )
        crawler = RemoteCrawler(base_url=service.base_url)

        async with crawler.crawl(url=service.base_url, download_files=True) as crawl:
            list(crawl.pages)
            assert list(crawl.files) == []

        assert service.file_requests == []


class TestFilenameForLink:
    def test_sanitizes_and_dedupes(self):
        taken: set[str] = set()
        first = _filename_for_link("https://k.se/docs/r%20apport.pdf", taken, 0)
        second = _filename_for_link("https://k.se/other/r apport.pdf", taken, 1)
        assert first == "r_apport.pdf"
        assert second == "1_r_apport.pdf"

    def test_fallback_for_extensionless_root(self):
        assert _filename_for_link("https://k.se/", set(), 7) == "file-7"


class TestValidateSitemapSource:
    """Rejection requires definitive evidence (seed reachable, discovery
    empty); anything unverifiable passes so a flaky preview never blocks
    configuration."""

    PREVIEW_FOUND = {
        "seed": {"reachable": True},
        "sitemap": {
            "found": True,
            "locations": ["https://k.se/sitemap.xml"],
            "url_count": 12,
            "total_urls_in_sitemap": 12,
        },
    }
    PREVIEW_OUT_OF_SCOPE = {
        "seed": {"reachable": True},
        "sitemap": {
            "found": True,
            "locations": ["https://k.se/sitemap.xml"],
            "url_count": 0,
            "total_urls_in_sitemap": 12,
        },
    }
    PREVIEW_NOT_FOUND = {
        "seed": {"reachable": True},
        "sitemap": {"found": False, "locations": []},
    }
    PREVIEW_UNREACHABLE = {
        "seed": {"reachable": False},
        "sitemap": {"found": False, "locations": []},
    }

    @pytest.mark.asyncio
    async def test_discovered_sitemap_is_valid(self, service):
        service.preview_response = self.PREVIEW_FOUND
        crawler = RemoteCrawler(base_url=service.base_url)

        validation = await crawler.validate_sitemap_source("https://k.se")

        assert validation.valid is True
        assert service.preview_received_json["crawl_type"] == "sitemap"
        assert service.preview_received_json["url"] == "https://k.se"

    @pytest.mark.asyncio
    async def test_reachable_site_without_sitemap_is_rejected(self, service):
        service.preview_response = self.PREVIEW_NOT_FOUND
        crawler = RemoteCrawler(base_url=service.base_url)

        validation = await crawler.validate_sitemap_source("https://k.se")

        assert validation.valid is False
        assert "no sitemap" in (validation.reason or "")

    @pytest.mark.asyncio
    async def test_sitemap_with_no_urls_in_seed_scope_is_rejected(self, service):
        service.preview_response = self.PREVIEW_OUT_OF_SCOPE
        crawler = RemoteCrawler(base_url=service.base_url)

        validation = await crawler.validate_sitemap_source("https://k.se/sitemap.xml")

        assert validation.valid is False
        assert "path scope" in (validation.reason or "")

    @pytest.mark.asyncio
    async def test_unreachable_site_passes(self, service):
        service.preview_response = self.PREVIEW_UNREACHABLE
        crawler = RemoteCrawler(base_url=service.base_url)

        validation = await crawler.validate_sitemap_source("https://k.se")

        assert validation.valid is True

    @pytest.mark.asyncio
    async def test_preview_error_passes(self, service):
        service.preview_status = 500
        crawler = RemoteCrawler(base_url=service.base_url)

        validation = await crawler.validate_sitemap_source("https://k.se")

        assert validation.valid is True

    @pytest.mark.asyncio
    async def test_unreachable_service_passes(self):
        crawler = RemoteCrawler(base_url="http://127.0.0.1:1")

        validation = await crawler.validate_sitemap_source("https://k.se")

        assert validation.valid is True

    @pytest.mark.asyncio
    async def test_http_auth_uses_wire_field_names(self, service):
        service.preview_response = self.PREVIEW_FOUND
        crawler = RemoteCrawler(base_url=service.base_url)

        await crawler.validate_sitemap_source(
            "https://k.se", http_user="u", http_pass="p"
        )

        assert service.preview_received_json["http_auth"] == {
            "user": "u",
            "password": "p",
        }


class TestDiscoverSitemapLocations:
    """discover_sitemap_locations surfaces the service's sitemap discovery so
    Eneo can fingerprint the real sitemap; any failure degrades to [] so the
    caller full-crawls instead of skipping on bad data."""

    FOUND = {
        "seed": {"reachable": True},
        "sitemap": {
            "found": True,
            "locations": ["https://k.se/sitemap.xml", "https://k.se/news.xml"],
            "url_count": 12,
        },
    }

    @pytest.mark.asyncio
    async def test_returns_locations_when_found(self, service):
        service.preview_response = self.FOUND
        crawler = RemoteCrawler(base_url=service.base_url)

        locations = await crawler.discover_sitemap_locations("https://k.se")

        assert locations == ["https://k.se/sitemap.xml", "https://k.se/news.xml"]
        assert service.preview_received_json["crawl_type"] == "sitemap"

    @pytest.mark.asyncio
    async def test_not_found_returns_empty(self, service):
        service.preview_response = {
            "seed": {"reachable": True},
            "sitemap": {"found": False, "locations": []},
        }
        crawler = RemoteCrawler(base_url=service.base_url)

        assert await crawler.discover_sitemap_locations("https://k.se") == []

    @pytest.mark.asyncio
    async def test_found_but_no_locations_field_returns_empty(self, service):
        service.preview_response = {"sitemap": {"found": True}}
        crawler = RemoteCrawler(base_url=service.base_url)

        assert await crawler.discover_sitemap_locations("https://k.se") == []

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self, service):
        service.preview_status = 500
        crawler = RemoteCrawler(base_url=service.base_url)

        assert await crawler.discover_sitemap_locations("https://k.se") == []

    @pytest.mark.asyncio
    async def test_unreachable_service_returns_empty(self):
        crawler = RemoteCrawler(base_url="http://127.0.0.1:1")

        assert await crawler.discover_sitemap_locations("https://k.se") == []

    @pytest.mark.asyncio
    async def test_non_string_locations_filtered_out(self, service):
        service.preview_response = {
            "sitemap": {
                "found": True,
                "locations": ["https://k.se/sitemap.xml", None, 42, ""],
            }
        }
        crawler = RemoteCrawler(base_url=service.base_url)

        locations = await crawler.discover_sitemap_locations("https://k.se")

        assert locations == ["https://k.se/sitemap.xml"]


class TestCreateCrawler:
    def test_returns_remote_when_url_configured(self):
        with patch(
            "eneo.main.config.get_settings",
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
            "eneo.main.config.get_settings",
            return_value=SimpleNamespace(
                crawler_service_url=None, crawler_service_api_key=None
            ),
        ):
            with pytest.raises(CrawlerException, match="CRAWLER_SERVICE_URL"):
                create_crawler()
