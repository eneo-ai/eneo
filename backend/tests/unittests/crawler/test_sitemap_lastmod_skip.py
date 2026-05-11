import importlib
from datetime import datetime, timezone

import scrapy
from scrapy.http import Request, XmlResponse

from intric.crawler.spiders.sitemap_spider import SitemapSpider, SourceRetainedUrl


class _SitemapEntries(list[dict[str, str]]):
    def __init__(self, entries: list[dict[str, str]], sitemap_type: str) -> None:
        super().__init__(entries)
        self.type = sitemap_type


def test_scrapy_sitemap_api_used_by_source_retention_exists():
    scrapy_sitemap = importlib.import_module("scrapy.utils.sitemap")

    assert hasattr(scrapy.spiders.SitemapSpider, "_get_sitemap_body")
    assert hasattr(scrapy_sitemap, "Sitemap")
    assert hasattr(scrapy_sitemap, "sitemap_urls_from_robots")


def test_sitemap_filter_skips_stale_allowed_url_and_records_retention():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/stable"],
    )
    entries = _SitemapEntries(
        [
            {
                "loc": "https://example.com/stable",
                "lastmod": "2026-05-09T12:00:00Z",
            },
            {
                "loc": "https://example.com/fresh",
                "lastmod": "2026-05-11T12:00:00Z",
            },
        ],
        sitemap_type="urlset",
    )

    filtered_entries = list(spider.sitemap_filter(entries))

    assert filtered_entries == [
        {
            "loc": "https://example.com/fresh",
            "lastmod": "2026-05-11T12:00:00Z",
        }
    ]
    assert spider.source_retained_urls == frozenset({"https://example.com/stable"})


def test_sitemap_filter_fetches_stale_url_without_allowed_existing_state():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=[],
    )
    entries = _SitemapEntries(
        [{"loc": "https://example.com/new-to-us", "lastmod": "2026-05-09"}],
        sitemap_type="urlset",
    )

    assert list(spider.sitemap_filter(entries)) == [
        {"loc": "https://example.com/new-to-us", "lastmod": "2026-05-09"}
    ]
    assert spider.source_retained_urls == frozenset()


def test_sitemap_filter_fetches_entries_without_parseable_lastmod():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/unknown"],
    )
    entries = _SitemapEntries(
        [{"loc": "https://example.com/unknown", "lastmod": "not-a-date"}],
        sitemap_type="urlset",
    )

    assert list(spider.sitemap_filter(entries)) == [
        {"loc": "https://example.com/unknown", "lastmod": "not-a-date"}
    ]
    assert spider.source_retained_urls == frozenset()


def test_sitemap_filter_does_not_skip_sitemap_index_entries():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/nested-sitemap.xml"],
    )
    entries = _SitemapEntries(
        [
            {
                "loc": "https://example.com/nested-sitemap.xml",
                "lastmod": "2026-05-09T12:00:00Z",
            }
        ],
        sitemap_type="sitemapindex",
    )

    assert list(spider.sitemap_filter(entries)) == [
        {
            "loc": "https://example.com/nested-sitemap.xml",
            "lastmod": "2026-05-09T12:00:00Z",
        }
    ]
    assert spider.source_retained_urls == frozenset()


def test_sitemap_filter_records_retained_urls_across_multiple_urlsets():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=[
            "https://example.com/stable-a",
            "https://example.com/stable-b",
        ],
    )

    list(
        spider.sitemap_filter(
            _SitemapEntries(
                [{"loc": "https://example.com/stable-a", "lastmod": "2026-05-09"}],
                sitemap_type="urlset",
            )
        )
    )
    list(
        spider.sitemap_filter(
            _SitemapEntries(
                [{"loc": "https://example.com/stable-b", "lastmod": "2026-05-09"}],
                sitemap_type="urlset",
            )
        )
    )

    assert spider.source_retained_urls == frozenset(
        {"https://example.com/stable-a", "https://example.com/stable-b"}
    )


def test_parse_sitemap_emits_source_retained_feed_item_and_fetches_fresh_url():
    spider = SitemapSpider(
        sitemap_url="https://example.com/sitemap.xml",
        lastmod_skip_cutoff=datetime(2026, 5, 10, tzinfo=timezone.utc),
        lastmod_skip_allowed_urls=["https://example.com/stable"],
    )
    response = XmlResponse(
        url="https://example.com/sitemap.xml",
        body=b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url>
            <loc>https://example.com/stable</loc>
            <lastmod>2026-05-09T12:00:00Z</lastmod>
          </url>
          <url>
            <loc>https://example.com/fresh</loc>
            <lastmod>2026-05-11T12:00:00Z</lastmod>
          </url>
        </urlset>""",
        encoding="utf-8",
    )

    outputs = list(spider._parse_sitemap(response))

    assert SourceRetainedUrl(url="https://example.com/stable") in outputs
    assert [output.url for output in outputs if isinstance(output, Request)] == [
        "https://example.com/fresh"
    ]
