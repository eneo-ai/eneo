from intric.crawler.crawler import CrawlDiagnostics


def test_empty_output_diagnostics_explains_no_requests() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats({})

    assert diagnostics.describe_empty_output() == (
        "Scrapy did not issue any requests; check crawler startup and runner setup"
    )


def test_empty_output_diagnostics_explains_robots_block() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 3,
            "robotstxt/forbidden": 2,
            "robotstxt/response_status_count/200": 1,
        }
    )

    assert diagnostics.describe_empty_output() == (
        "robots.txt blocked 2 request(s); robots responses: 200=1"
    )


def test_empty_output_diagnostics_explains_downloader_exceptions() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 1,
            "downloader/exception_type_count/twisted.internet.error.DNSLookupError": 1,
        }
    )

    assert diagnostics.describe_empty_output() == (
        "downloader exceptions: twisted.internet.error.DNSLookupError=1"
    )


def test_empty_output_diagnostics_explains_feed_export_mismatch() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 2,
            "downloader/response_count": 2,
            "downloader/response_status_count/200": 2,
            "item_scraped_count": 4,
            "file_count": 1,
            "file_status_count/downloaded": 1,
        }
    )

    assert diagnostics.describe_empty_output() == (
        "Scrapy scraped 4 item(s), but no page items reached the page feed; "
        "check FEEDS item_classes and item pipelines"
    )


def test_diagnostics_extracts_files_skipped_by_download_size_limit() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 3,
            "file_status_count/downloaded": 1,
            "file_status_count/too_large": 2,
        }
    )

    assert diagnostics.file_status_counts == {"downloaded": 1, "too_large": 2}
    assert diagnostics.files_too_large_skipped_count == 2
    assert diagnostics.to_log_fields()["file_status_counts"] == {
        "downloaded": 1,
        "too_large": 2,
    }


def test_empty_output_diagnostics_summarizes_status_codes() -> None:
    diagnostics = CrawlDiagnostics.from_scrapy_stats(
        {
            "downloader/request_count": 2,
            "downloader/response_count": 2,
            "downloader/response_status_count/403": 1,
            "downloader/response_status_count/500": 1,
            "finish_reason": "finished",
        }
    )

    assert diagnostics.describe_empty_output() == (
        "responses received but no page items scraped; HTTP statuses: 403=1, 500=1; "
        "finish_reason=finished"
    )
