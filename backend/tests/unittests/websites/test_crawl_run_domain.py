from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from intric.main.models import Status
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawl_run import CrawlFileTooLargeSample, CrawlRun
from intric.websites.domain.crawl_run_repo import _serialize_crawl_outcome_code
from intric.websites.presentation.website_models import (
    CrawlRunPublic as PresentationCrawlRunPublic,
)


def _crawl_run_record(
    *,
    outcome_code: str | None,
    pages_source_retained: int | None = None,
    pages_hash_retained: int | None = None,
    files_hash_retained: int | None = None,
    files_too_large_skipped: int | None = None,
    files_too_large_download_limit_bytes: int | None = None,
    files_too_large_samples: list[dict[str, int | str | None]] | None = None,
):
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
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        files_too_large_download_limit_bytes=files_too_large_download_limit_bytes,
        files_too_large_samples=files_too_large_samples,
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


def test_crawl_run_domain_maps_pages_source_retained():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(outcome_code=None, pages_source_retained=7)
    )

    assert crawl_run.pages_source_retained == 7


def test_crawl_run_domain_maps_hash_retained_counts():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(
            outcome_code=None,
            pages_hash_retained=3,
            files_hash_retained=1,
        )
    )

    assert crawl_run.pages_hash_retained == 3
    assert crawl_run.files_hash_retained == 1


def test_crawl_run_domain_maps_files_too_large_skipped():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(outcome_code=None, files_too_large_skipped=2)
    )

    assert crawl_run.files_too_large_skipped == 2


def test_crawl_run_domain_maps_too_large_file_samples():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(
            outcome_code=None,
            files_too_large_download_limit_bytes=10_485_760,
            files_too_large_samples=[
                {
                    "url": "https://example.com/large.pdf",
                    "observed_size_bytes": 19_746_387,
                }
            ],
        )
    )

    assert crawl_run.files_too_large_download_limit_bytes == 10_485_760
    assert crawl_run.files_too_large_samples == (
        CrawlFileTooLargeSample(
            url="https://example.com/large.pdf",
            observed_size_bytes=19_746_387,
        ),
    )


def test_crawl_run_domain_tolerates_legacy_null_too_large_file_samples():
    crawl_run = CrawlRun.to_domain(
        record=_crawl_run_record(
            outcome_code=None,
            files_too_large_download_limit_bytes=None,
            files_too_large_samples=None,
        )
    )

    assert crawl_run.files_too_large_download_limit_bytes is None
    assert crawl_run.files_too_large_samples == ()


def test_crawl_run_create_defaults_pages_source_retained_to_none():
    website = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    crawl_run = CrawlRun.create(website=website)

    assert crawl_run.pages_source_retained is None
    assert crawl_run.pages_hash_retained is None
    assert crawl_run.files_hash_retained is None
    assert crawl_run.files_too_large_skipped is None
    assert crawl_run.files_too_large_download_limit_bytes is None
    assert crawl_run.files_too_large_samples == ()


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
        pages_source_retained=None,
        pages_hash_retained=None,
        files_hash_retained=None,
        files_too_large_skipped=None,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
        failure_summary=None,
        outcome_code=None,
    )

    crawl_run.update(outcome_code=CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED)

    assert crawl_run.outcome_code == CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED


def test_crawl_run_update_accepts_pages_source_retained():
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
        pages_source_retained=None,
        pages_hash_retained=None,
        files_hash_retained=None,
        files_too_large_skipped=None,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
        failure_summary=None,
        outcome_code=None,
    )

    crawl_run.update(pages_source_retained=5)

    assert crawl_run.pages_source_retained == 5


def test_crawl_run_update_accepts_hash_retained_counts():
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
        pages_source_retained=None,
        pages_hash_retained=None,
        files_hash_retained=None,
        files_too_large_skipped=None,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
        failure_summary=None,
        outcome_code=None,
    )

    crawl_run.update(pages_hash_retained=4, files_hash_retained=2)

    assert crawl_run.pages_hash_retained == 4
    assert crawl_run.files_hash_retained == 2


def test_crawl_run_update_accepts_files_too_large_skipped():
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
        pages_source_retained=None,
        pages_hash_retained=None,
        files_hash_retained=None,
        files_too_large_skipped=None,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
        failure_summary=None,
        outcome_code=None,
    )

    crawl_run.update(files_too_large_skipped=3)

    assert crawl_run.files_too_large_skipped == 3


def test_crawl_run_update_accepts_too_large_file_sample_fields():
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
        pages_source_retained=None,
        pages_hash_retained=None,
        files_hash_retained=None,
        files_too_large_skipped=None,
        status=Status.QUEUED,
        result_location=None,
        finished_at=None,
        job_id=None,
    )

    crawl_run.update(
        files_too_large_download_limit_bytes=10_485_760,
        files_too_large_samples=(
            CrawlFileTooLargeSample(
                url="https://example.com/large.pdf",
                observed_size_bytes=19_746_387,
            ),
        ),
    )

    assert crawl_run.files_too_large_download_limit_bytes == 10_485_760
    assert crawl_run.files_too_large_samples == (
        CrawlFileTooLargeSample(
            url="https://example.com/large.pdf",
            observed_size_bytes=19_746_387,
        ),
    )


def test_presentation_crawl_run_public_exposes_pages_source_retained():
    now = datetime.now(timezone.utc)
    crawl_run = CrawlRun(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        website_id=uuid4(),
        tenant_id=uuid4(),
        pages_crawled=0,
        files_downloaded=0,
        pages_failed=0,
        files_failed=0,
        pages_source_retained=8,
        pages_hash_retained=0,
        files_hash_retained=0,
        files_too_large_skipped=0,
        status=Status.COMPLETE,
        result_location=None,
        finished_at=now,
        job_id=uuid4(),
        failure_summary=None,
        outcome_code=CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY,
    )

    public = PresentationCrawlRunPublic.from_domain(crawl_run)

    assert public.pages_source_retained == 8
    assert public.outcome is not None
    assert public.outcome.affected_count == 8


def test_presentation_crawl_run_public_exposes_processing_summary():
    now = datetime.now(timezone.utc)
    crawl_run = CrawlRun(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        website_id=uuid4(),
        tenant_id=uuid4(),
        pages_crawled=300,
        files_downloaded=4,
        pages_failed=0,
        files_failed=1,
        pages_source_retained=12,
        pages_hash_retained=290,
        files_hash_retained=1,
        files_too_large_skipped=2,
        files_too_large_download_limit_bytes=10_485_760,
        files_too_large_samples=(
            CrawlFileTooLargeSample(
                url="https://example.com/large.pdf",
                observed_size_bytes=19_746_387,
            ),
        ),
        status=Status.COMPLETE,
        result_location=None,
        finished_at=now,
        job_id=uuid4(),
        failure_summary=None,
        outcome_code=None,
    )

    public = PresentationCrawlRunPublic.from_domain(crawl_run)

    assert public.pages_hash_retained == 290
    assert public.files_hash_retained == 1
    assert public.files_too_large_skipped == 2
    assert public.files_too_large_download_limit_bytes == 10_485_760
    assert len(public.files_too_large_samples) == 1
    assert public.files_too_large_samples[0].url == "https://example.com/large.pdf"
    assert public.files_too_large_samples[0].observed_size_bytes == 19_746_387
    assert public.processing_summary is not None
    assert public.processing_summary.pages_fetched == 300
    assert public.processing_summary.pages_indexed == 10
    assert public.processing_summary.pages_hash_retained == 290
    assert public.processing_summary.pages_source_retained == 12
    assert public.processing_summary.files_downloaded == 4
    assert public.processing_summary.files_indexed == 2
    assert public.processing_summary.files_hash_retained == 1
    assert public.processing_summary.files_too_large_skipped == 2
    assert public.processing_summary.files_failed == 1


def test_crawl_run_repository_serializes_outcome_code_for_database():
    assert (
        _serialize_crawl_outcome_code(CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED)
        == "CRAWL_DUPLICATE_SKIPPED"
    )
    assert _serialize_crawl_outcome_code(None) is None
