import gzip
import hashlib

import pytest

from eneo.crawler.sitemap import InvalidSitemap, parse_sitemap, snapshot_sitemap


def test_empty_urlset_has_an_authoritative_snapshot() -> None:
    parsed = parse_sitemap(
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" />'
    )

    snapshot = snapshot_sitemap(list(parsed.entries))

    assert snapshot is not None
    assert snapshot.entry_count == 0
    assert snapshot.fingerprint == hashlib.sha256(b"").hexdigest()


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


def test_parse_sitemap_accepts_standard_optional_fields_and_extensions() -> None:
    body = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
      <url>
        <loc>https://example.se/one</loc>
        <lastmod>2026-09-02</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.8</priority>
        <image:image><image:loc>https://example.se/one.jpg</image:loc></image:image>
      </url>
    </urlset>"""

    assert parse_sitemap(body).structurally_complete is True


def test_parse_sitemap_rejects_entity_declarations() -> None:
    body = b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><urlset />'

    with pytest.raises(InvalidSitemap, match="entity"):
        parse_sitemap(body)


def test_parse_sitemap_skips_entry_without_location_and_marks_incomplete() -> None:
    parsed = parse_sitemap(
        b"<urlset>"
        b"<url><lastmod>2026-09-02</lastmod></url>"
        b"<url><loc>https://example.se/valid</loc></url>"
        b"</urlset>"
    )

    assert parsed.locations == ("https://example.se/valid",)
    assert parsed.structurally_complete is False


@pytest.mark.parametrize(
    "body",
    [
        (
            b"<sitemapindex><sitemap>hidden"
            b"<loc>https://example.com/empty.xml</loc></sitemap></sitemapindex>"
        ),
        (
            b"<sitemapindex><sitemap>"
            b"<loc>https://example.com/populated.xml</loc>"
            b"<loc>https://example.com/empty.xml</loc>"
            b"</sitemap></sitemapindex>"
        ),
        (
            b"<sitemapindex><sitemap>"
            b"<loc>https://example.com/empty.xml</loc>"
            b"<unexpected><loc>https://example.com/populated.xml</loc></unexpected>"
            b"</sitemap></sitemapindex>"
        ),
    ],
    ids=("item-text", "duplicate-loc", "unexpected-core-child"),
)
def test_parse_sitemap_marks_discarded_core_item_content_incomplete(
    body: bytes,
) -> None:
    assert parse_sitemap(body).structurally_complete is False


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
