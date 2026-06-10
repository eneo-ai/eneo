"""Unit tests for sitemap fingerprinting (scheduled-crawl short-circuit).

The probe must be conservative: anything it cannot fully and soundly
fingerprint (fetch failures, nested indexes, missing lastmod) must either
return None or a probe with supports_skip=False, so the crawl proceeds.
"""

import gzip
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from intric.crawler.sitemap_check import probe_sitemap, state_is_fresh

URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://k.se/a</loc><lastmod>2026-06-01</lastmod></url>
  <url><loc>https://k.se/b?x=1&amp;y=2</loc><lastmod>2026-06-02</lastmod></url>
</urlset>
"""

URLSET_REORDERED = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://k.se/b?x=1&amp;y=2</loc><lastmod>2026-06-02</lastmod></url>
  <url><loc>https://k.se/a</loc><lastmod>2026-06-01</lastmod></url>
</urlset>
"""

URLSET_NO_LASTMOD = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://k.se/a</loc></url>
</urlset>
"""


class SitemapStub:
    """Serves configurable XML documents by path."""

    def __init__(self):
        self.docs: dict[str, bytes] = {}
        self.status: int = 200
        self.base_url: str = ""

    async def handle(self, request: web.Request) -> web.Response:
        if self.status != 200:
            return web.Response(status=self.status)
        body = self.docs.get(request.path)
        if body is None:
            return web.Response(status=404)
        content_type = (
            "application/gzip" if request.path.endswith(".gz") else "application/xml"
        )
        return web.Response(body=body, content_type=content_type)


@pytest.fixture
async def stub():
    stub = SitemapStub()
    app = web.Application()
    app.router.add_get("/{tail:.*}", stub.handle)
    server = TestServer(app)
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    yield stub
    await server.close()


class TestProbeSitemap:
    @pytest.mark.asyncio
    async def test_urlset_with_lastmod_supports_skip(self, stub):
        stub.docs["/sitemap.xml"] = URLSET.encode()

        probe = await probe_sitemap(f"{stub.base_url}/sitemap.xml")

        assert probe is not None
        assert probe.entry_count == 2
        assert probe.lastmod_count == 2
        assert probe.supports_skip is True

    @pytest.mark.asyncio
    async def test_fingerprint_is_order_independent(self, stub):
        stub.docs["/a.xml"] = URLSET.encode()
        stub.docs["/b.xml"] = URLSET_REORDERED.encode()

        probe_a = await probe_sitemap(f"{stub.base_url}/a.xml")
        probe_b = await probe_sitemap(f"{stub.base_url}/b.xml")

        assert probe_a is not None and probe_b is not None
        assert probe_a.fingerprint == probe_b.fingerprint

    @pytest.mark.asyncio
    async def test_lastmod_change_changes_fingerprint(self, stub):
        stub.docs["/a.xml"] = URLSET.encode()
        stub.docs["/b.xml"] = URLSET.replace("2026-06-02", "2026-06-03").encode()

        probe_a = await probe_sitemap(f"{stub.base_url}/a.xml")
        probe_b = await probe_sitemap(f"{stub.base_url}/b.xml")

        assert probe_a is not None and probe_b is not None
        assert probe_a.fingerprint != probe_b.fingerprint

    @pytest.mark.asyncio
    async def test_urlset_without_lastmod_never_skips(self, stub):
        stub.docs["/sitemap.xml"] = URLSET_NO_LASTMOD.encode()

        probe = await probe_sitemap(f"{stub.base_url}/sitemap.xml")

        assert probe is not None
        assert probe.lastmod_count == 0
        assert probe.supports_skip is False

    @pytest.mark.asyncio
    async def test_index_aggregates_sub_sitemaps(self, stub):
        index = f"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{stub.base_url}/sub1.xml</loc></sitemap>
          <sitemap><loc>{stub.base_url}/sub2.xml</loc></sitemap>
        </sitemapindex>
        """
        stub.docs["/index.xml"] = index.encode()
        stub.docs["/sub1.xml"] = URLSET.encode()
        stub.docs["/sub2.xml"] = URLSET_NO_LASTMOD.encode()

        probe = await probe_sitemap(f"{stub.base_url}/index.xml")

        assert probe is not None
        assert probe.entry_count == 3
        assert probe.lastmod_count == 2

    @pytest.mark.asyncio
    async def test_nested_index_fails_probe(self, stub):
        index = f"""<sitemapindex>
          <sitemap><loc>{stub.base_url}/inner.xml</loc></sitemap>
        </sitemapindex>"""
        stub.docs["/index.xml"] = index.encode()
        stub.docs["/inner.xml"] = index.encode()

        assert await probe_sitemap(f"{stub.base_url}/index.xml") is None

    @pytest.mark.asyncio
    async def test_missing_sub_sitemap_fails_probe(self, stub):
        index = f"""<sitemapindex>
          <sitemap><loc>{stub.base_url}/gone.xml</loc></sitemap>
        </sitemapindex>"""
        stub.docs["/index.xml"] = index.encode()

        assert await probe_sitemap(f"{stub.base_url}/index.xml") is None

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, stub):
        stub.status = 503

        assert await probe_sitemap(f"{stub.base_url}/sitemap.xml") is None

    @pytest.mark.asyncio
    async def test_gzipped_sitemap_is_decoded(self, stub):
        stub.docs["/sitemap.xml.gz"] = gzip.compress(URLSET.encode())

        probe = await probe_sitemap(f"{stub.base_url}/sitemap.xml.gz")

        assert probe is not None
        assert probe.entry_count == 2


class TestStateIsFresh:
    def _state(self, age: timedelta) -> dict:
        crawled_at = datetime.now(timezone.utc) - age
        return {"fingerprint": "abc", "crawled_at": crawled_at.isoformat()}

    def test_recent_state_is_fresh(self):
        assert state_is_fresh(self._state(timedelta(hours=24)), max_age_hours=168)

    def test_state_older_than_window_forces_recrawl(self):
        assert not state_is_fresh(self._state(timedelta(hours=169)), max_age_hours=168)

    def test_missing_or_malformed_crawled_at_is_never_fresh(self):
        assert not state_is_fresh({}, max_age_hours=168)
        assert not state_is_fresh({"crawled_at": "not-a-date"}, max_age_hours=168)
