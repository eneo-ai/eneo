import gzip

import pytest

from eneo.crawler.sitemap import InvalidSitemap, parse_sitemap


def test_parse_sitemap_handles_namespaces_and_gzip() -> None:
    body = gzip.compress(
        b"""<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://example.se/one</loc></url>
          <url><loc>https://example.se/two</loc></url>
        </urlset>"""
    )

    parsed = parse_sitemap(body)

    assert parsed.kind == "urlset"
    assert parsed.locations == (
        "https://example.se/one",
        "https://example.se/two",
    )


def test_parse_sitemap_rejects_entity_declarations() -> None:
    body = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><urlset />'

    with pytest.raises(InvalidSitemap, match="entity"):
        parse_sitemap(body)


def test_parse_sitemap_bounds_gzip_expansion() -> None:
    body = gzip.compress(b"<urlset>" + b" " * 10_000 + b"</urlset>")

    with pytest.raises(InvalidSitemap, match="size limit"):
        parse_sitemap(body, max_decompressed_bytes=100)
