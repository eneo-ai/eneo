import logging

import pytest

from intric.websites.crawl_dependencies.crawl_models import CrawlRunProcessingSummary
from intric.worker.crawl.completion_log import emit_crawl_completion_logs


def test_completion_log_counts_source_retained_pages_as_retained(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.crawl_completion_log.source_retained")
    summary = CrawlRunProcessingSummary(
        pages_fetched=0,
        pages_source_retained=5,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        emit_crawl_completion_logs(
            logger=logger,
            url="https://example.com/sitemap.xml",
            processing_summary=summary,
            blobs_deleted=0,
            timings={
                "fetch_existing_titles": 0.01,
                "crawl_and_parse": 0.02,
                "process_pages": 0.0,
                "process_files": 0.0,
                "cleanup_deleted": 0.0,
                "update_size": 0.0,
            },
            crawl_termination_reason=None,
        )

    performance_record = _performance_record(caplog.records)
    assert performance_record.page_skip_rate_percent == 100.0
    summary_message = _summary_record(caplog.records).getMessage()
    assert "5 source-retained" in summary_message
    assert "100.0% retained" in summary_message


def test_completion_log_exposes_structured_retention_and_file_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.crawl_completion_log.metrics")
    summary = CrawlRunProcessingSummary(
        pages_fetched=10,
        pages_hash_retained=7,
        pages_source_retained=2,
        pages_failed=1,
        files_downloaded=6,
        files_hash_retained=3,
        files_failed=1,
        files_too_large_skipped=2,
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        emit_crawl_completion_logs(
            logger=logger,
            url="https://example.com/",
            processing_summary=summary,
            blobs_deleted=4,
            timings={
                "fetch_existing_titles": 1.0,
                "crawl_and_parse": 2.0,
                "process_pages": 3.0,
                "process_files": 4.0,
                "cleanup_deleted": 5.0,
                "update_size": 6.0,
            },
            crawl_termination_reason=None,
        )

    performance_record = _performance_record(caplog.records)
    assert performance_record.pages_hash_retained == 7
    assert performance_record.pages_source_retained == 2
    assert performance_record.files_hash_retained == 3
    assert performance_record.files_too_large_skipped == 2
    assert performance_record.page_skip_rate_percent == 75.0
    assert performance_record.file_skip_rate_percent == 62.5
    assert performance_record.blobs_deleted == 4


def test_completion_log_includes_partial_termination_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.crawl_completion_log.partial")
    summary = CrawlRunProcessingSummary(pages_fetched=3)

    with caplog.at_level(logging.INFO, logger=logger.name):
        emit_crawl_completion_logs(
            logger=logger,
            url="https://example.com/",
            processing_summary=summary,
            blobs_deleted=0,
            timings={
                "fetch_existing_titles": 0.0,
                "crawl_and_parse": 9.0,
                "process_pages": 1.0,
                "process_files": 0.0,
                "cleanup_deleted": 0.0,
                "update_size": 0.0,
            },
            crawl_termination_reason="timeout",
        )

    summary_message = _summary_record(caplog.records).getMessage()
    assert "CRAWL PARTIAL (timeout): https://example.com/" in summary_message
    assert "Partial completion due to: timeout" in summary_message


def test_completion_log_handles_empty_processing_summary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("test.crawl_completion_log.empty")

    with caplog.at_level(logging.INFO, logger=logger.name):
        emit_crawl_completion_logs(
            logger=logger,
            url="https://example.com/",
            processing_summary=CrawlRunProcessingSummary(),
            blobs_deleted=0,
            timings={
                "fetch_existing_titles": 0.0,
                "crawl_and_parse": 0.0,
                "process_pages": 0.0,
                "process_files": 0.0,
                "cleanup_deleted": 0.0,
                "update_size": 0.0,
            },
            crawl_termination_reason=None,
        )

    performance_record = _performance_record(caplog.records)
    assert performance_record.page_skip_rate_percent == 0.0
    assert performance_record.file_skip_rate_percent == 0.0
    summary_message = _summary_record(caplog.records).getMessage()
    assert "CRAWL FINISHED: https://example.com/" in summary_message
    assert "Partial completion due to:" not in summary_message


def _summary_record(records: list[logging.LogRecord]) -> logging.LogRecord:
    for record in records:
        if record.getMessage().startswith("=" * 60):
            return record
    raise AssertionError("Completion summary log record not found")


def _performance_record(records: list[logging.LogRecord]) -> logging.LogRecord:
    for record in records:
        if record.getMessage().startswith("Performance breakdown:"):
            return record
    raise AssertionError("Performance breakdown log record not found")
