import importlib
import re
from datetime import datetime, timezone

import scrapy
from scrapy.http import Request, XmlResponse

from intric.crawler.spiders.sitemap_spider import SitemapSpider, SourceRetainedUrl


def _xml_response(body: bytes) -> XmlResponse:
    return XmlResponse(
        url="https://example.com/sitemap.xml",
        body=body,
        encoding="utf-8",
    )


def _request_urls(outputs: list[object]) -> list[str]:
    return [output.url for output in outputs if isinstance(output, Request)]


def _source_retained_urls(outputs: list[object]) -> set[str]:
    return {
        output.url for output in outputs if isinstance(output, SourceRetainedUrl)
    }


def test_scrapy_sitemap_api_used_by_source_retention_exists():
    scrapy_sitemap = importlib.import_module("scrapy.utils.sitemap")

    assert hasattr(scrapy.spiders.SitemapSpider, "_get_sitemap_body")
    assert hasattr(scrapy_sitemap, "Sitemap")
    assert hasattr(scrapy_sitemap, "sitemap_urls_from_robots")


def test_parse_sitemap_retains_stale_allowed_url_and_fetches_fresh_url():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/stable"],
    )
    response = _xml_response(
        b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/stable</loc>
            <lastmod>2026-05-09T12:00:00Z</lastmod>
          </url>
          <url>
            <loc>https://example.com/fresh</loc>
            <lastmod>2026-05-11T12:00:00Z</lastmod>
          </url>
        </urlset>"""
    )

    outputs = list(spider._parse_sitemap(response))

    assert _source_retained_urls(outputs) == {"https://example.com/stable"}
    assert _request_urls(outputs) == ["https://example.com/fresh"]
    assert spider.source_retained_urls == frozenset({"https://example.com/stable"})


def test_parse_sitemap_fetches_stale_url_without_allowed_existing_state():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=[],
    )
    response = _xml_response(
        b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/new-to-us</loc>
            <lastmod>2026-05-09</lastmod>
          </url>
        </urlset>"""
    )

    outputs = list(spider._parse_sitemap(response))

    assert _source_retained_urls(outputs) == set()
    assert _request_urls(outputs) == ["https://example.com/new-to-us"]
    assert spider.source_retained_urls == frozenset()


def test_parse_sitemap_fetches_entries_without_parseable_lastmod():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/unknown"],
    )
    response = _xml_response(
        b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/unknown</loc>
            <lastmod>not-a-date</lastmod>
          </url>
        </urlset>"""
    )

    outputs = list(spider._parse_sitemap(response))

    assert _source_retained_urls(outputs) == set()
    assert _request_urls(outputs) == ["https://example.com/unknown"]
    assert spider.source_retained_urls == frozenset()


def test_parse_sitemap_does_not_source_retain_sitemap_index_entries():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/nested-sitemap.xml"],
    )
    spider._follow = [re.compile("")]
    response = _xml_response(
        b"""<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap>
            <loc>https://example.com/nested-sitemap.xml</loc>
            <lastmod>2026-05-09T12:00:00Z</lastmod>
          </sitemap>
        </sitemapindex>"""
    )

    outputs = list(spider._parse_sitemap(response))

    assert _source_retained_urls(outputs) == set()
    assert _request_urls(outputs) == ["https://example.com/nested-sitemap.xml"]
    assert spider.source_retained_urls == frozenset()


def test_parse_sitemap_records_retained_urls_across_multiple_urlsets():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=[
            "https://example.com/stable-a",
            "https://example.com/stable-b",
        ],
    )

    first_outputs = list(
        spider._parse_sitemap(
            _xml_response(
                b"""<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url>
                    <loc>https://example.com/stable-a</loc>
                    <lastmod>2026-05-09</lastmod>
                  </url>
                </urlset>"""
            )
        )
    )
    second_outputs = list(
        spider._parse_sitemap(
            _xml_response(
                b"""<?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url>
                    <loc>https://example.com/stable-b</loc>
                    <lastmod>2026-05-09</lastmod>
                  </url>
                </urlset>"""
            )
        )
    )

    assert _source_retained_urls(first_outputs) == {"https://example.com/stable-a"}
    assert _source_retained_urls(second_outputs) == {"https://example.com/stable-b"}
    assert spider.source_retained_urls == frozenset(
        {"https://example.com/stable-a", "https://example.com/stable-b"}
    )


def test_parse_sitemap_deduplicates_source_retained_feed_items():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/stable"],
    )
    response = _xml_response(
        body=b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/stable</loc>
            <lastmod>2026-05-09T12:00:00Z</lastmod>
          </url>
        </urlset>""",
    )

    first_outputs = list(spider._parse_sitemap(response))
    second_outputs = list(spider._parse_sitemap(response))

    assert _source_retained_urls(first_outputs) == {"https://example.com/stable"}
    assert _source_retained_urls(second_outputs) == set()
    assert spider.source_retained_urls == frozenset({"https://example.com/stable"})
