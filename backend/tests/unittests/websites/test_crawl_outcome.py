from intric.main.models import Status
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlOutcomeCode,
    CrawlOutcomeSeverity,
    derive_crawl_outcome,
)
from intric.worker.crawl_context import FailureReason


def test_duplicate_crawl_skip_is_info_outcome():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="Skipped duplicate crawl: already running",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED
    assert outcome.severity == CrawlOutcomeSeverity.INFO
    assert outcome.message_key == "crawl_outcome_duplicate_skipped"


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
