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

from eneo.crawler.sitemap_check import probe_sitemap, state_is_fresh
from eneo.crawler.url_scope import host_of

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
        # (path, Authorization header) for every document fetch served
        self.requests: list[tuple[str, str | None]] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append((request.path, request.headers.get("Authorization")))
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


async def _other_host_server(docs: dict[str, bytes]) -> TestServer:
    """A second test server on a distinct host:port from the ``stub`` fixture,
    for asserting cross-host probe behavior. Caller must ``await .close()``."""

    async def handle(request: web.Request) -> web.Response:
        body = docs.get(request.path)
        if body is None:
            return web.Response(status=404)
        return web.Response(body=body, content_type="application/xml")

    app = web.Application()
    app.router.add_get("/{tail:.*}", handle)
    server = TestServer(app)
    await server.start_server()
    server.base_url = str(server.make_url("")).rstrip("/")  # type: ignore[attr-defined]
    return server


class TestProbeSitemap:
    @pytest.mark.asyncio
    async def test_no_locations_returns_none(self, stub):
        # Discovery found nothing -> no fingerprint, caller full-crawls
        assert await probe_sitemap([]) is None

    @pytest.mark.asyncio
    async def test_urlset_with_lastmod_supports_skip(self, stub):
        stub.docs["/sitemap.xml"] = URLSET.encode()

        probe = await probe_sitemap([f"{stub.base_url}/sitemap.xml"])

        assert probe is not None
        assert probe.entry_count == 2
        assert probe.lastmod_count == 2
        assert probe.supports_skip is True

    @pytest.mark.asyncio
    async def test_fingerprint_is_order_independent(self, stub):
        stub.docs["/a.xml"] = URLSET.encode()
        stub.docs["/b.xml"] = URLSET_REORDERED.encode()

        probe_a = await probe_sitemap([f"{stub.base_url}/a.xml"])
        probe_b = await probe_sitemap([f"{stub.base_url}/b.xml"])

        assert probe_a is not None and probe_b is not None
        assert probe_a.fingerprint == probe_b.fingerprint

    @pytest.mark.asyncio
    async def test_lastmod_change_changes_fingerprint(self, stub):
        stub.docs["/a.xml"] = URLSET.encode()
        stub.docs["/b.xml"] = URLSET.replace("2026-06-02", "2026-06-03").encode()

        probe_a = await probe_sitemap([f"{stub.base_url}/a.xml"])
        probe_b = await probe_sitemap([f"{stub.base_url}/b.xml"])

        assert probe_a is not None and probe_b is not None
        assert probe_a.fingerprint != probe_b.fingerprint

    @pytest.mark.asyncio
    async def test_urlset_without_lastmod_never_skips(self, stub):
        stub.docs["/sitemap.xml"] = URLSET_NO_LASTMOD.encode()

        probe = await probe_sitemap([f"{stub.base_url}/sitemap.xml"])

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

        probe = await probe_sitemap([f"{stub.base_url}/index.xml"])

        assert probe is not None
        assert probe.entry_count == 3
        assert probe.lastmod_count == 2
        # One entry (from sub2) has no lastmod, so a change on that page would
        # leave the fingerprint identical; the mixed sitemap must not skip.
        assert probe.supports_skip is False

    @pytest.mark.asyncio
    async def test_entry_cap_crossed_by_sub_sitemaps_fails_probe(
        self, stub, monkeypatch
    ):
        # The probe retains every (loc, lastmod) entry before fingerprinting;
        # the probe-wide cap bounds that memory. Crossing it mid-index gives
        # up (full crawl) instead of aggregating further.
        import eneo.crawler.sitemap_check as sitemap_check

        monkeypatch.setattr(sitemap_check, "_MAX_TOTAL_ENTRIES", 3)
        index = f"""<?xml version="1.0"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{stub.base_url}/sub1.xml</loc></sitemap>
          <sitemap><loc>{stub.base_url}/sub2.xml</loc></sitemap>
        </sitemapindex>
        """
        stub.docs["/index.xml"] = index.encode()
        stub.docs["/sub1.xml"] = URLSET.encode()
        stub.docs["/sub2.xml"] = URLSET.encode()

        assert await probe_sitemap([f"{stub.base_url}/index.xml"]) is None

    @pytest.mark.asyncio
    async def test_entry_cap_crossed_across_locations_fails_probe(
        self, stub, monkeypatch
    ):
        # The cap is probe-wide: entries already collected from earlier
        # top-level locations shrink the budget for later ones.
        import eneo.crawler.sitemap_check as sitemap_check

        monkeypatch.setattr(sitemap_check, "_MAX_TOTAL_ENTRIES", 3)
        stub.docs["/a.xml"] = URLSET.encode()
        stub.docs["/b.xml"] = URLSET.encode()

        assert (
            await probe_sitemap([f"{stub.base_url}/a.xml", f"{stub.base_url}/b.xml"])
            is None
        )

    @pytest.mark.asyncio
    async def test_mixed_lastmod_never_skips(self, stub):
        # A urlset where one of two entries lacks lastmod: the fingerprint is
        # blind to changes on the lastmod-less page, so skipping is unsound.
        mixed = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://k.se/a</loc><lastmod>2026-06-01</lastmod></url>
          <url><loc>https://k.se/b</loc></url>
        </urlset>
        """
        stub.docs["/sitemap.xml"] = mixed.encode()

        probe = await probe_sitemap([f"{stub.base_url}/sitemap.xml"])

        assert probe is not None
        assert probe.entry_count == 2
        assert probe.lastmod_count == 1
        assert probe.supports_skip is False

    @pytest.mark.asyncio
    async def test_multiple_locations_combine_into_one_fingerprint(self, stub):
        # A site can declare several top-level sitemaps; their entries are
        # unioned and the fingerprint is independent of location order.
        stub.docs["/a.xml"] = URLSET.encode()
        stub.docs["/b.xml"] = URLSET_NO_LASTMOD.encode()
        a = f"{stub.base_url}/a.xml"
        b = f"{stub.base_url}/b.xml"

        probe_ab = await probe_sitemap([a, b])
        probe_ba = await probe_sitemap([b, a])

        assert probe_ab is not None and probe_ba is not None
        # URLSET (2 entries) + URLSET_NO_LASTMOD (1 entry), order-independent
        assert probe_ab.entry_count == 3
        assert probe_ab.lastmod_count == 2
        assert probe_ab.fingerprint == probe_ba.fingerprint

    @pytest.mark.asyncio
    async def test_on_host_location_carries_auth(self, stub):
        # A discovered sitemap on the auth host receives the site credentials
        stub.docs["/sitemap.xml"] = URLSET.encode()

        probe = await probe_sitemap(
            [f"{stub.base_url}/sitemap.xml"],
            auth_host=host_of(stub.base_url),
            http_user="intern",
            http_pass="hemligt",
        )

        assert probe is not None and probe.entry_count == 2
        assert [path for path, _ in stub.requests] == ["/sitemap.xml"]
        assert stub.requests[0][1] is not None
        assert stub.requests[0][1].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_off_auth_host_location_under_auth_fails_probe(self, stub):
        # A discovered location off the auth host must not receive credentials;
        # the conservative choice is to fail the probe (full crawl) without
        # ever contacting the off-host URL.
        probe = await probe_sitemap(
            ["http://other.host.invalid/sitemap.xml"],
            auth_host=host_of(stub.base_url),
            http_user="intern",
            http_pass="hemligt",
        )

        assert probe is None
        assert stub.requests == []

    @pytest.mark.asyncio
    async def test_off_auth_host_sub_sitemap_under_auth_fails_probe(self, stub):
        # An index on the auth host listing an off-host sub-sitemap fails the
        # probe before the off-host URL is contacted.
        index = """<sitemapindex>
          <sitemap><loc>http://other.host.invalid/sub.xml</loc></sitemap>
        </sitemapindex>"""
        stub.docs["/index.xml"] = index.encode()

        probe = await probe_sitemap(
            [f"{stub.base_url}/index.xml"],
            auth_host=host_of(stub.base_url),
            http_user="intern",
            http_pass="hemligt",
        )

        assert probe is None
        # Only the on-host index was fetched (with auth); the off-host
        # sub-sitemap was never contacted
        assert [path for path, _ in stub.requests] == ["/index.xml"]
        assert stub.requests[0][1] is not None
        assert stub.requests[0][1].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_off_host_location_without_auth_is_fetched(self, stub):
        # Without credentials there is nothing to leak, so a sitemap on another
        # host (apex/www, CDN) is fetched normally.
        other = await _other_host_server({"/sitemap.xml": URLSET.encode()})
        try:
            probe = await probe_sitemap([f"{other.base_url}/sitemap.xml"])

            assert probe is not None
            assert probe.entry_count == 2
        finally:
            await other.close()

    @pytest.mark.asyncio
    async def test_nested_index_fails_probe(self, stub):
        index = f"""<sitemapindex>
          <sitemap><loc>{stub.base_url}/inner.xml</loc></sitemap>
        </sitemapindex>"""
        stub.docs["/index.xml"] = index.encode()
        stub.docs["/inner.xml"] = index.encode()

        assert await probe_sitemap([f"{stub.base_url}/index.xml"]) is None

    @pytest.mark.asyncio
    async def test_missing_sub_sitemap_fails_probe(self, stub):
        index = f"""<sitemapindex>
          <sitemap><loc>{stub.base_url}/gone.xml</loc></sitemap>
        </sitemapindex>"""
        stub.docs["/index.xml"] = index.encode()

        assert await probe_sitemap([f"{stub.base_url}/index.xml"]) is None

    @pytest.mark.asyncio
    async def test_non_200_returns_none(self, stub):
        stub.status = 503

        assert await probe_sitemap([f"{stub.base_url}/sitemap.xml"]) is None

    @pytest.mark.asyncio
    async def test_gzipped_sitemap_is_decoded(self, stub):
        stub.docs["/sitemap.xml.gz"] = gzip.compress(URLSET.encode())

        probe = await probe_sitemap([f"{stub.base_url}/sitemap.xml.gz"])

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
