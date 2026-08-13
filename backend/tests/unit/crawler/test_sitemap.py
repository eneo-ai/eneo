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


def test_parse_sitemap_rejects_declaration_padded_past_prefix() -> None:
    body = b" " * 5000 + (
        b"<!DOCTYPE urlset [<!ENTITY x 'https://example.se/expanded'>]>"
        b"<urlset><url><loc>&x;</loc></url></urlset>"
    )

    with pytest.raises(InvalidSitemap, match="entity"):
        parse_sitemap(body)


def test_parse_sitemap_rejects_utf16_declaration_bypass() -> None:
    body = (
        "<!DOCTYPE urlset [<!ENTITY x 'https://example.se/expanded'>]>"
        "<urlset><url><loc>&x;</loc></url></urlset>"
    ).encode("utf-16")

    with pytest.raises(InvalidSitemap, match="encoding"):
        parse_sitemap(body)


def test_parse_sitemap_normalizes_truncated_gzip() -> None:
    body = gzip.compress(b"<urlset />")[:-4]

    with pytest.raises(InvalidSitemap, match="invalid gzip"):
        parse_sitemap(body)
