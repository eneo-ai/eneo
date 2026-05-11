from intric.main.models import Status
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlOutcomeSeverity,
    CrawlRunSparse,
    derive_crawl_outcome,
    derive_crawl_outcome_code,
)
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.worker.crawl_context import FailureReason


def test_stored_duplicate_crawl_skip_is_info_outcome_without_string_parsing():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="active job 123",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
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


def test_embedding_failure_summary_becomes_config_outcome():
    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary={FailureReason.NO_EMBEDDING_MODEL.value: 2},
        pages_failed=2,
        files_failed=0,
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
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_no_pages_returned"


def test_stored_max_age_outcome_has_specific_error_message():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="crawl waited past the configured maximum age",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
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
        outcome_code=CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY
    assert outcome.severity == CrawlOutcomeSeverity.INFO
    assert outcome.message_key == "crawl_outcome_source_retention_only"


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
