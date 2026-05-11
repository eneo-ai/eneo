from intric.main.models import Status
from intric.websites.crawl_dependencies import crawl_models
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlOutcomeSeverity,
    CrawlRunSparse,
    derive_crawl_outcome,
    derive_crawl_outcome_code,
)
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    FailureReason,
    classify_crawl_outcome,
)


def test_stored_duplicate_crawl_skip_is_info_outcome_without_string_parsing():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="active job 123",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
        outcome_code=CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED
    assert outcome.severity == CrawlOutcomeSeverity.INFO
    assert outcome.message_key == "crawl_outcome_duplicate_skipped"


def test_legacy_duplicate_crawl_skip_string_still_derives_outcome():
    outcome_code = derive_crawl_outcome_code(
        status=Status.FAILED,
        result_location="Skipped duplicate crawl: already running",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
    )

    assert outcome_code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED


def test_legacy_outcome_fallback_emits_observability(monkeypatch):
    class CapturingLogger:
        def __init__(self):
            self.extra: dict[str, object] | None = None

        def info(self, _message: str, *, extra: dict[str, object]) -> None:
            self.extra = extra

    logger = CapturingLogger()
    monkeypatch.setattr(crawl_models, "logger", logger)

    outcome_code = derive_crawl_outcome_code(
        status=Status.FAILED,
        result_location="Crawl timed out before collecting pages",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
    )

    assert outcome_code == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES
    assert logger.extra == {
        "metric_name": "crawler.outcome.legacy_fallback_used",
        "metric_value": 1,
        "outcome_code": CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES.value,
    }


def test_embedding_failure_summary_becomes_config_outcome():
    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary={FailureReason.NO_EMBEDDING_MODEL.value: 2},
        pages_failed=2,
        files_failed=0,
        pages_source_retained=None,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING
    assert outcome.severity == CrawlOutcomeSeverity.WARNING
    assert outcome.affected_count == 2


def test_failed_no_pages_result_location_becomes_typed_error():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="Crawl failed for https://example.com: no pages returned",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_no_pages_returned"


def test_stored_sitemap_no_pages_outcome_has_specific_message():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="Crawl failed for https://example.com: no pages returned",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
        outcome_code=CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_sitemap_no_pages"


def test_stored_max_age_outcome_has_specific_error_message():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="crawl waited past the configured maximum age",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
        outcome_code=CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_max_age_exceeded"


def test_stored_source_retention_outcome_is_informational():
    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=None,
        outcome_code=CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY
    assert outcome.severity == CrawlOutcomeSeverity.INFO
    assert outcome.message_key == "crawl_outcome_source_retention_only"


def test_stored_partial_timeout_outcome_is_warning():
    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=12,
        outcome_code=CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT
    assert outcome.severity == CrawlOutcomeSeverity.WARNING
    assert outcome.message_key == "crawl_outcome_partial_timeout"


def test_source_retention_outcome_uses_source_retained_count():
    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=42,
        outcome_code=CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
    )

    assert outcome is not None
    assert outcome.affected_count == 42


def test_page_failure_outcome_does_not_use_source_retained_count_as_affected_count():
    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary={FailureReason.DB_ERROR.value: 2},
        pages_failed=2,
        files_failed=0,
        pages_source_retained=100,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
    assert outcome.affected_count == 2


def test_classify_completed_crawl_with_no_pages_returned():
    assert (
        classify_crawl_outcome(
            crawl_type="crawl",
            is_partial=False,
            termination_reason="completed",
            pages_count=0,
            source_retained_count=0,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
        )
        == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    )


def test_classify_completed_sitemap_with_no_pages_returned():
    assert (
        classify_crawl_outcome(
            crawl_type="sitemap",
            is_partial=False,
            termination_reason="completed",
            pages_count=0,
            source_retained_count=0,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
        )
        == CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES
    )


def test_classify_timeout_without_output():
    assert (
        classify_crawl_outcome(
            crawl_type="sitemap",
            is_partial=True,
            termination_reason="timeout",
            pages_count=0,
            source_retained_count=0,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
        )
        == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES
    )


def test_classify_partial_timeout_with_output_takes_run_level_precedence():
    assert (
        classify_crawl_outcome(
            crawl_type="sitemap",
            is_partial=True,
            termination_reason="timeout",
            pages_count=3,
            source_retained_count=100,
            failure_summary={FailureReason.DB_ERROR.value: 2},
            pages_failed=2,
            files_failed=0,
        )
        == CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT
    )


def test_classify_source_retention_only():
    assert (
        classify_crawl_outcome(
            crawl_type="sitemap",
            is_partial=False,
            termination_reason="completed",
            pages_count=0,
            source_retained_count=42,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
        )
        == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY
    )


def test_classify_embedding_failure_summary():
    assert (
        classify_crawl_outcome(
            crawl_type="crawl",
            is_partial=False,
            termination_reason="completed",
            pages_count=5,
            source_retained_count=0,
            failure_summary={FailureReason.MISSING_PROVIDER.value: 2},
            pages_failed=2,
            files_failed=0,
        )
        == CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING
    )


def test_crawl_run_sparse_uses_stored_outcome_code():
    crawl_run = CrawlRunSparse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "created_at": None,
            "updated_at": None,
            "status": Status.FAILED,
            "result_location": "active job 123",
            "outcome_code": CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
        }
    )

    assert crawl_run.outcome is not None
    assert crawl_run.outcome.code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED


def test_crawl_run_sparse_source_retention_outcome_uses_retained_count():
    crawl_run = CrawlRunSparse.model_validate(
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "created_at": None,
            "updated_at": None,
            "status": Status.COMPLETE,
            "result_location": None,
            "pages_failed": 0,
            "files_failed": 0,
            "pages_source_retained": 12,
            "outcome_code": CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
        }
    )

    assert crawl_run.outcome is not None
    assert crawl_run.outcome.affected_count == 12
