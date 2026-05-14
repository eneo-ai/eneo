import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from intric.main.models import Status
from intric.websites.crawl_dependencies import crawl_models
from intric.websites.crawl_dependencies.crawl_models import (
    CrawlOutcomeSeverity,
    CrawlRunSparse,
    derive_crawl_outcome,
    derive_crawl_outcome_code,
    derive_crawl_processing_summary,
)
from intric.websites.domain import crawl_outcome
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    FailureReason,
    classify_crawl_outcome,
    parse_crawl_outcome_code_lenient,
    parse_crawl_outcome_code_strict,
    parse_failure_summary_lenient,
    parse_failure_summary_strict,
    serialize_failure_summary_for_storage,
)
from intric.websites.presentation.website_models import (
    CrawlRunPublic as WebsiteCrawlRunPublic,
)


def test_write_side_outcome_parser_rejects_unknown_values():
    with pytest.raises(ValueError, match="UNKNOWN_NEW_OUTCOME"):
        parse_crawl_outcome_code_strict("UNKNOWN_NEW_OUTCOME")


def test_historical_outcome_parser_keeps_safe_unknown_fallback():
    assert (
        parse_crawl_outcome_code_lenient("UNKNOWN_LEGACY_OUTCOME")
        == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR
    )


def test_historical_failure_summary_parser_drops_unknown_keys_and_reports_them():
    dropped_keys: list[str] = []

    parsed = parse_failure_summary_lenient(
        {
            FailureReason.EMPTY_CONTENT.value: 3,
            "UNKNOWN_LEGACY_BUCKET": 1,
        },
        on_unknown_key=dropped_keys.append,
    )

    assert parsed == {FailureReason.EMPTY_CONTENT: 3}
    assert dropped_keys == ["UNKNOWN_LEGACY_BUCKET"]


def test_historical_failure_summary_unknown_key_emits_observability(monkeypatch):
    class CapturingLogger:
        def __init__(self):
            self.extra: dict[str, object] | None = None

        def info(self, _message: str, *, extra: dict[str, object]) -> None:
            self.extra = extra

    logger = CapturingLogger()
    monkeypatch.setattr(crawl_outcome, "logger", logger)

    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary={
            FailureReason.DB_ERROR.value: 1,
            "UNKNOWN_LEGACY_BUCKET": 1,
        },
        pages_failed=1,
        files_failed=0,
        pages_source_retained=None,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
    assert logger.extra == {
        "metric_name": "crawler.failure_summary.legacy_key_dropped",
        "metric_value": 1,
        "failure_reason": "UNKNOWN_LEGACY_BUCKET",
    }


def test_write_side_failure_summary_parser_rejects_unknown_keys():
    with pytest.raises(ValueError, match="UNKNOWN_NEW_BUCKET"):
        parse_failure_summary_strict({"UNKNOWN_NEW_BUCKET": 1})


def test_write_side_failure_summary_parser_accepts_enum_keys_and_string_aliases():
    parsed_from_enum_keys = parse_failure_summary_strict(
        {FailureReason.EMPTY_CONTENT: 3}
    )
    parsed_from_string_aliases = parse_failure_summary_strict(
        {FailureReason.MISSING_PROVIDER.value: 2}
    )

    assert parsed_from_enum_keys == {FailureReason.EMPTY_CONTENT: 3}
    assert parsed_from_string_aliases == {FailureReason.MISSING_PROVIDER: 2}


def test_failure_summary_storage_serialization_keeps_existing_json_shape():
    summary = parse_failure_summary_strict(
        {
            FailureReason.DB_ERROR: 2,
            FailureReason.MISSING_PROVIDER: 1,
        }
    )

    assert serialize_failure_summary_for_storage(summary) == {
        "DB_ERROR": 2,
        "MISSING_PROVIDER": 1,
    }


def test_crawl_run_public_serializes_failure_summary_with_string_keys():
    public_run = WebsiteCrawlRunPublic(
        id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        pages_crawled=2,
        files_downloaded=0,
        pages_failed=2,
        files_failed=0,
        pages_source_retained=0,
        pages_hash_retained=0,
        files_hash_retained=0,
        files_too_large_skipped=0,
        failure_summary={FailureReason.DB_ERROR: 2},
        outcome_code=CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
        status=Status.COMPLETE,
        result_location=None,
        finished_at=datetime.now(timezone.utc),
    )

    dumped = public_run.model_dump(mode="json")

    assert dumped["failure_summary"] == {"DB_ERROR": 2}


def test_crawl_outcome_public_parity_fixture():
    fixture_path = Path(__file__).parents[2] / "fixtures" / "crawl_outcome_parity.json"
    cases = json.loads(fixture_path.read_text())

    for case in cases:
        input_data = case["input"]
        if "processing_summary" in input_data:
            input_data = {
                **input_data,
                "processing_summary": crawl_models.CrawlRunProcessingSummary(
                    **input_data["processing_summary"]
                ),
            }
        outcome = derive_crawl_outcome(**input_data)
        if outcome is None:
            actual = None
        else:
            actual = outcome.model_dump(mode="json")

        assert actual == case["expected"], case["name"]


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


def test_stored_outcome_code_does_not_call_legacy_fallback(monkeypatch):
    def fail_legacy_fallback(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("stored outcome_code must not use legacy fallback")

    monkeypatch.setattr(
        crawl_models,
        "derive_outcome_from_legacy_columns",
        fail_legacy_fallback,
    )

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


def test_unknown_stored_outcome_code_does_not_call_legacy_fallback(monkeypatch):
    def fail_legacy_fallback(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("stored outcome_code must not use legacy fallback")

    monkeypatch.setattr(
        crawl_models,
        "derive_outcome_from_legacy_columns",
        fail_legacy_fallback,
    )

    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="worker exited unexpectedly",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
        outcome_code="FUTURE_OUTCOME",
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR
    assert outcome.detail == "worker exited unexpectedly"


def test_legacy_unknown_failure_preserves_detail_without_specific_outcome():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="worker exited unexpectedly",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR
    assert outcome.detail == "worker exited unexpectedly"


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


def test_processing_summary_partitions_indexed_hash_retained_and_failed_counts():
    summary = derive_crawl_processing_summary(
        pages_crawled=300,
        files_downloaded=4,
        pages_failed=0,
        files_failed=1,
        pages_source_retained=12,
        pages_hash_retained=290,
        files_hash_retained=1,
        files_too_large_skipped=2,
    )

    assert summary.pages_fetched == 300
    assert summary.pages_indexed == 10
    assert summary.pages_hash_retained == 290
    assert summary.pages_source_retained == 12
    assert summary.files_downloaded == 4
    assert summary.files_indexed == 2
    assert summary.files_hash_retained == 1
    assert summary.files_too_large_skipped == 2
    assert summary.files_failed == 1


def test_processing_summary_logs_invalid_count_invariant(monkeypatch):
    class CapturingLogger:
        def __init__(self):
            self.extra: dict[str, object] | None = None

        def warning(self, _message: str, *, extra: dict[str, object]) -> None:
            self.extra = extra

    logger = CapturingLogger()
    monkeypatch.setattr(crawl_models, "logger", logger)

    summary = derive_crawl_processing_summary(
        pages_crawled=2,
        files_downloaded=0,
        pages_failed=1,
        files_failed=0,
        pages_source_retained=0,
        pages_hash_retained=2,
        files_hash_retained=0,
        files_too_large_skipped=0,
    )

    assert summary.pages_indexed == 0
    assert logger.extra == {
        "metric_name": "crawler.processing_summary.invalid_count_invariant",
        "metric_value": 1,
        "resource_type": "pages",
        "total": 2,
        "hash_retained": 2,
        "failed": 1,
    }


def test_completed_run_with_only_hash_retained_content_is_all_unchanged():
    processing_summary = derive_crawl_processing_summary(
        pages_crawled=3,
        files_downloaded=1,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=0,
        pages_hash_retained=3,
        files_hash_retained=1,
        files_too_large_skipped=0,
    )

    outcome = derive_crawl_outcome(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=0,
        pages_hash_retained=3,
        files_hash_retained=1,
        files_too_large_skipped=0,
        processing_summary=processing_summary,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_ALL_UNCHANGED
    assert outcome.severity == CrawlOutcomeSeverity.INFO
    assert outcome.message_key == "crawl_outcome_all_unchanged"
    assert outcome.affected_count == 4


def test_completed_run_with_hash_retained_content_still_needs_summary_for_all_unchanged():
    outcome_code = derive_crawl_outcome_code(
        status=Status.COMPLETE,
        result_location=None,
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
        pages_hash_retained=3,
        files_hash_retained=1,
    )

    assert outcome_code is None


def test_completed_run_with_only_too_large_files_has_specific_outcome():
    outcome_code = classify_crawl_outcome(
        crawl_type="crawl",
        is_partial=False,
        termination_reason="completed",
        pages_count=0,
        files_count=0,
        source_retained_count=0,
        files_too_large_skipped=3,
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
    )

    assert outcome_code == CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY


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


def test_stored_runtime_timeout_outcome_has_specific_error_message():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="Crawl exceeded the maximum runtime of 12 hours and was stopped",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
        outcome_code=CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_runtime_timeout"


def test_stored_queue_enqueue_failure_outcome_has_specific_error_message():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="Failed to add crawl to pending queue: Redis unavailable",
        failure_summary=None,
        pages_failed=None,
        files_failed=None,
        pages_source_retained=None,
        outcome_code=CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_QUEUE_ENQUEUE_FAILED
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_queue_enqueue_failed"


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


def test_stored_shutdown_outcome_has_specific_error_message():
    outcome = derive_crawl_outcome(
        status=Status.FAILED,
        result_location="Scrapy reactor did not stop cleanly",
        failure_summary=None,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=0,
        outcome_code=CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR,
    )

    assert outcome is not None
    assert outcome.code == CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR
    assert outcome.severity == CrawlOutcomeSeverity.ERROR
    assert outcome.message_key == "crawl_outcome_shutdown_error"
    assert outcome.detail == "Scrapy reactor did not stop cleanly"


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


def test_classify_partial_timeout_with_embedding_failure_keeps_timeout_precedence():
    assert (
        classify_crawl_outcome(
            crawl_type="sitemap",
            is_partial=True,
            termination_reason="timeout",
            pages_count=3,
            source_retained_count=0,
            failure_summary={FailureReason.MISSING_PROVIDER.value: 2},
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


def test_classify_all_unchanged_crawl():
    assert (
        classify_crawl_outcome(
            crawl_type="crawl",
            is_partial=False,
            termination_reason="completed",
            pages_count=3,
            files_count=1,
            source_retained_count=0,
            pages_hash_retained=3,
            files_hash_retained=1,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
        )
        == CrawlOutcomeCode.CRAWL_ALL_UNCHANGED
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
