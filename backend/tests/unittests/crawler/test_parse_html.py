from types import SimpleNamespace

from eneo.crawler.parse_html import (
    CRAWLABLE_DOCUMENT_MIMETYPES,
    parse_file,
)


def _response(content_type: str, url: str = "https://example.com/doc"):
    # parse_file only touches .headers.get(b"Content-Type") and .url
    return SimpleNamespace(
        headers={b"Content-Type": content_type.encode()},
        url=url,
    )


class TestParseFileCrawlPolicy:
    """parse_file decides which linked files a crawl ingests as documents."""

    def test_ingests_supported_documents(self):
        for ct in ["application/pdf", "application/json", "text/xml", "text/csv"]:
            assert parse_file(_response(ct)) == {
                "file_urls": ["https://example.com/doc"]
            }, ct

    def test_skips_html_pages(self):
        # HTML is handled by parse_response as a page, never downloaded as a file.
        assert parse_file(_response("text/html")) is None
        assert "text/html" not in CRAWLABLE_DOCUMENT_MIMETYPES

    def test_skips_legacy_office_formats(self):
        # Legacy .doc/.ppt are rejected by the extractor, so don't waste a download.
        assert parse_file(_response("application/msword")) is None
        assert parse_file(_response("application/vnd.ms-powerpoint")) is None

    def test_skips_unknown_types(self):
        assert parse_file(_response("application/octet-stream")) is None
        assert parse_file(_response("image/png")) is None

    def test_handles_charset_suffix(self):
        assert parse_file(_response("application/pdf; charset=binary")) is not None

    def test_falls_back_to_extension_when_no_content_type(self):
        resp = SimpleNamespace(headers={}, url="https://example.com/report.pdf")
        assert parse_file(resp) == {"file_urls": ["https://example.com/report.pdf"]}
