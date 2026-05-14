import json
from collections.abc import Mapping
from pathlib import Path

from intric.main.models import Status
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    FailureReason,
    parse_failure_summary_lenient,
)
from intric.websites.domain.crawl_outcome_legacy_fallback import (
    LegacyCrawlOutcomeInput,
    derive_outcome_from_legacy_columns,
)


def _legacy_input_from_fixture(
    input_data: Mapping[str, object],
) -> LegacyCrawlOutcomeInput:
    processing_summary = input_data.get("processing_summary")
    indexed_count: int | None = None
    if isinstance(processing_summary, dict):
        indexed_count = int(processing_summary["pages_indexed"]) + int(
            processing_summary["files_indexed"]
        )

    return LegacyCrawlOutcomeInput(
        status=_optional_str(input_data.get("status")),
        result_location=_optional_str(input_data.get("result_location")),
        failure_summary=_optional_failure_summary(input_data.get("failure_summary")),
        pages_failed=_optional_int(input_data.get("pages_failed")),
        files_failed=_optional_int(input_data.get("files_failed")),
        pages_hash_retained=_optional_int(input_data.get("pages_hash_retained")),
        files_hash_retained=_optional_int(input_data.get("files_hash_retained")),
        files_too_large_skipped=_optional_int(
            input_data.get("files_too_large_skipped")
        ),
        indexed_count=indexed_count,
    )


def _optional_str(value: object) -> str | None:
    assert value is None or isinstance(value, str)
    return value


def _optional_int(value: object) -> int | None:
    assert value is None or isinstance(value, int)
    return value


def _optional_failure_summary(value: object) -> dict[FailureReason, int] | None:
    assert value is None or isinstance(value, dict)
    if value is None:
        return None

    return parse_failure_summary_lenient(
        {str(key): int(count) for key, count in value.items()}
    )


def test_legacy_fallback_matches_parity_fixture_for_rows_without_stored_outcome():
    fixture_path = Path(__file__).parents[2] / "fixtures" / "crawl_outcome_parity.json"
    cases = json.loads(fixture_path.read_text())

    for case in cases:
        input_data = case["input"]
        if "outcome_code" in input_data:
            continue

        fallback = derive_outcome_from_legacy_columns(
            _legacy_input_from_fixture(input_data)
        )

        if case["expected"] is None:
            assert fallback.outcome_code is None, case["name"]
            continue

        assert fallback.outcome_code == CrawlOutcomeCode(case["expected"]["code"]), (
            case["name"]
        )


def test_legacy_duplicate_result_location_maps_to_duplicate_outcome():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.FAILED,
            result_location="Skipped duplicate crawl: already running",
            failure_summary=None,
            pages_failed=None,
            files_failed=None,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED
    assert fallback.metric_code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED


def test_legacy_failure_summary_maps_to_embedding_config_outcome():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.COMPLETE,
            result_location=None,
            failure_summary={FailureReason.MISSING_PROVIDER: 2},
            pages_failed=2,
            files_failed=0,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING
    assert fallback.metric_code == CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING


def test_legacy_complete_all_unchanged_counter_outcome_does_not_emit_metric():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.COMPLETE,
            result_location=None,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
            pages_hash_retained=3,
            files_hash_retained=1,
            indexed_count=0,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.CRAWL_ALL_UNCHANGED
    assert fallback.metric_code is None


def test_legacy_unknown_failed_row_maps_to_unknown_with_metric():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.FAILED,
            result_location="worker exited unexpectedly",
            failure_summary=None,
            pages_failed=None,
            files_failed=None,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR
    assert fallback.metric_code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR


def test_legacy_no_pages_result_location_maps_to_no_pages_outcome():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.FAILED,
            result_location="Crawl failed for https://example.com: no pages returned",
            failure_summary=None,
            pages_failed=None,
            files_failed=None,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED
    assert fallback.metric_code == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED


def test_legacy_timeout_result_location_maps_to_timeout_outcome():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.FAILED,
            result_location="Crawl timed out before collecting pages",
            failure_summary=None,
            pages_failed=None,
            files_failed=None,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES
    assert fallback.metric_code == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES


def test_legacy_too_large_only_counter_outcome_does_not_emit_metric():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.COMPLETE,
            result_location=None,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
            files_too_large_skipped=3,
            indexed_count=0,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY
    assert fallback.metric_code is None


def test_legacy_failed_counts_without_summary_map_to_page_failures():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.COMPLETE,
            result_location=None,
            failure_summary=None,
            pages_failed=2,
            files_failed=0,
        )
    )

    assert fallback.outcome_code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
    assert fallback.metric_code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES


def test_legacy_empty_completed_row_has_no_outcome():
    fallback = derive_outcome_from_legacy_columns(
        LegacyCrawlOutcomeInput(
            status=Status.COMPLETE,
            result_location=None,
            failure_summary=None,
            pages_failed=0,
            files_failed=0,
        )
    )

    assert fallback.outcome_code is None
    assert fallback.metric_code is None
