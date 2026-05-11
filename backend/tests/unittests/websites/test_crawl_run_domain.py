from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlRun
from intric.websites.domain.crawl_run_repo import _serialize_crawl_outcome_code


def _crawl_run_record(*, outcome_code: str | None):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        website_id=uuid4(),
        tenant_id=uuid4(),
        pages_crawled=0,
        files_downloaded=0,
        pages_failed=0,
        files_failed=0,
        job_id=uuid4(),
        job=SimpleNamespace(
            status=Status.FAILED.value,
            result_location="Skipped duplicate crawl: active job",
            finished_at=now,
        ),
        failure_summary=None,
        outcome_code=outcome_code,
    )


def test_crawl_run_domain_parses_stored_outcome_code_to_enum():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(
            outcome_code=CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED.value
        )
    )

    assert crawl_run.outcome_code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED


def test_crawl_run_domain_unknown_stored_outcome_code_is_safe_to_read():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(outcome_code="REMOVED_CODE")
    )

    assert crawl_run.outcome_code == CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR


def test_crawl_run_domain_keeps_legacy_null_outcome_code_for_derived_fallback():
    crawl_run = CrawlRun.to_domain(record=_crawl_run_record(outcome_code=None))

    assert crawl_run.outcome_code is None


def test_crawl_run_update_accepts_typed_outcome_code():
    crawl_run = CrawlRun(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        website_id=uuid4(),
        tenant_id=uuid4(),
        pages_crawled=None,
        files_downloaded=None,
        pages_failed=None,
        files_failed=None,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
        failure_summary=None,
        outcome_code=None,
    )

    crawl_run.update(outcome_code=CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED)

    assert crawl_run.outcome_code == CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED


def test_crawl_run_repository_serializes_outcome_code_for_database():
    assert (
        _serialize_crawl_outcome_code(CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED)
        == "CRAWL_DUPLICATE_SKIPPED"
    )
    assert _serialize_crawl_outcome_code(None) is None
