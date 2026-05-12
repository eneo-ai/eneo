from datetime import datetime
from enum import Enum
from typing import Literal, Optional, Self
from uuid import UUID

from pydantic import AliasChoices, AliasPath, BaseModel, Field, model_validator

from intric.jobs.task_models import TaskParams
from intric.main.logging import get_logger
from intric.main.models import InDB, Status
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    FailureReason,
    parse_crawl_outcome_code,
)
from intric.websites.domain.crawl_run import CrawlType

logger = get_logger(__name__)


class CrawlTask(TaskParams):
    website_id: UUID
    run_id: UUID
    url: str
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL


class CrawlRunBase(BaseModel):
    pages_crawled: Optional[int] = None
    files_downloaded: Optional[int] = None
    pages_failed: Optional[int] = None
    files_failed: Optional[int] = None
    pages_source_retained: Optional[int] = None
    pages_hash_retained: Optional[int] = None
    files_hash_retained: Optional[int] = None
    files_too_large_skipped: Optional[int] = None
    failure_summary: Optional[dict[str, int]] = None
    outcome_code: Optional["CrawlOutcomeCode"] = None


class CrawlRunProcessingSummary(BaseModel):
    pages_fetched: int = 0
    files_downloaded: int = 0
    pages_indexed: int = 0
    files_indexed: int = 0
    pages_hash_retained: int = 0
    files_hash_retained: int = 0
    files_too_large_skipped: int = 0
    pages_source_retained: int = 0
    pages_failed: int = 0
    files_failed: int = 0


def derive_crawl_processing_summary(
    *,
    pages_crawled: int | None,
    files_downloaded: int | None,
    pages_failed: int | None,
    files_failed: int | None,
    pages_source_retained: int | None,
    pages_hash_retained: int | None,
    files_hash_retained: int | None,
    files_too_large_skipped: int | None = None,
) -> CrawlRunProcessingSummary:
    pages_fetched = pages_crawled or 0
    downloaded_files = files_downloaded or 0
    failed_pages = pages_failed or 0
    failed_files = files_failed or 0
    source_retained_pages = pages_source_retained or 0
    hash_retained_pages = pages_hash_retained or 0
    hash_retained_files = files_hash_retained or 0
    too_large_skipped_files = files_too_large_skipped or 0

    return CrawlRunProcessingSummary(
        pages_fetched=pages_fetched,
        files_downloaded=downloaded_files,
        pages_indexed=_indexed_count(
            resource_type="pages",
            total=pages_fetched,
            hash_retained=hash_retained_pages,
            failed=failed_pages,
        ),
        files_indexed=_indexed_count(
            resource_type="files",
            total=downloaded_files,
            hash_retained=hash_retained_files,
            failed=failed_files,
        ),
        pages_hash_retained=hash_retained_pages,
        files_hash_retained=hash_retained_files,
        files_too_large_skipped=too_large_skipped_files,
        pages_source_retained=source_retained_pages,
        pages_failed=failed_pages,
        files_failed=failed_files,
    )


def _indexed_count(
    *,
    resource_type: Literal["pages", "files"],
    total: int,
    hash_retained: int,
    failed: int,
) -> int:
    indexed = total - hash_retained - failed
    if indexed >= 0:
        return indexed

    logger.warning(
        "Invalid crawl run count invariant while deriving processing summary",
        extra={
            "metric_name": "crawler.processing_summary.invalid_count_invariant",
            "metric_value": 1,
            "resource_type": resource_type,
            "total": total,
            "hash_retained": hash_retained,
            "failed": failed,
        },
    )
    return 0


class CrawlOutcomeSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CrawlOutcomePublic(BaseModel):
    code: CrawlOutcomeCode
    severity: CrawlOutcomeSeverity
    message_key: str
    detail: Optional[str] = None
    affected_count: Optional[int] = None
    samples: list[str] = Field(default_factory=list)


def derive_crawl_outcome(
    *,
    status: Status | str | None,
    result_location: str | None,
    failure_summary: dict[str, int] | None,
    pages_failed: int | None,
    files_failed: int | None,
    pages_source_retained: int | None,
    pages_hash_retained: int | None = None,
    files_hash_retained: int | None = None,
    files_too_large_skipped: int | None = None,
    processing_summary: CrawlRunProcessingSummary | None = None,
    outcome_code: CrawlOutcomeCode | str | None = None,
) -> CrawlOutcomePublic | None:
    resolved_code = (
        parse_crawl_outcome_code(outcome_code)
        if outcome_code is not None
        else derive_crawl_outcome_code(
            status=status,
            result_location=result_location,
            failure_summary=failure_summary,
            pages_failed=pages_failed,
            files_failed=files_failed,
            pages_hash_retained=pages_hash_retained,
            files_hash_retained=files_hash_retained,
            files_too_large_skipped=files_too_large_skipped,
            processing_summary=processing_summary,
        )
    )
    if resolved_code is None:
        return None

    return _crawl_outcome_from_code(
        code=resolved_code,
        result_location=result_location,
        failure_summary=failure_summary,
        pages_failed=pages_failed,
        files_failed=files_failed,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        processing_summary=processing_summary,
    )


def derive_crawl_outcome_code(
    *,
    status: Status | str | None,
    result_location: str | None,
    failure_summary: dict[str, int] | None,
    pages_failed: int | None,
    files_failed: int | None,
    pages_hash_retained: int | None = None,
    files_hash_retained: int | None = None,
    files_too_large_skipped: int | None = None,
    processing_summary: CrawlRunProcessingSummary | None = None,
) -> CrawlOutcomeCode | None:
    # Read-side fallback for historical rows without stored outcome_code. Keep
    # shared outcome rules aligned with the worker-time classifier in crawl_outcome.py.
    status_value = status.value if isinstance(status, Status) else status
    detail = result_location.strip() if result_location else None
    detail_lower = detail.lower() if detail else ""
    affected_count = (pages_failed or 0) + (files_failed or 0)
    hash_retained_count = (pages_hash_retained or 0) + (files_hash_retained or 0)
    too_large_count = files_too_large_skipped or 0
    indexed_count = 0
    if processing_summary is not None:
        hash_retained_count = (
            processing_summary.pages_hash_retained
            + processing_summary.files_hash_retained
        )
        indexed_count = (
            processing_summary.pages_indexed + processing_summary.files_indexed
        )
        too_large_count = processing_summary.files_too_large_skipped

    # Legacy rows only stored crawl outcomes in result_location text. New writes
    # should set outcome_code and use these branches only as a read fallback.
    if status_value == Status.FAILED.value and detail_lower.startswith(
        "skipped duplicate crawl"
    ):
        _log_legacy_outcome_fallback_used(CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED)
        return CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED

    if failure_summary:
        if (
            FailureReason.NO_EMBEDDING_MODEL.value in failure_summary
            or FailureReason.MISSING_PROVIDER.value in failure_summary
        ):
            _log_legacy_outcome_fallback_used(CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING)
            return CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING

        _log_legacy_outcome_fallback_used(
            CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
        )
        return CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES

    if status_value == Status.FAILED.value or status_value == Status.NOT_FOUND.value:
        if "no pages returned" in detail_lower:
            _log_legacy_outcome_fallback_used(CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED)
            return CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED

        if "timeout" in detail_lower or "timed out" in detail_lower:
            _log_legacy_outcome_fallback_used(CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES)
            return CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES

        _log_legacy_outcome_fallback_used(CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR)
        return CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR

    if (
        status_value == Status.COMPLETE.value
        and too_large_count > 0
        and indexed_count == 0
    ):
        return CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY

    if affected_count > 0:
        _log_legacy_outcome_fallback_used(
            CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES
        )
        return CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES

    if (
        status_value == Status.COMPLETE.value
        and processing_summary is not None
        and hash_retained_count > 0
        and indexed_count == 0
    ):
        return CrawlOutcomeCode.CRAWL_ALL_UNCHANGED

    return None


def _log_legacy_outcome_fallback_used(code: CrawlOutcomeCode) -> None:
    logger.info(
        "Derived crawl outcome for legacy crawl run without stored outcome_code",
        extra={
            "metric_name": "crawler.outcome.legacy_fallback_used",
            "metric_value": 1,
            "outcome_code": code.value,
        },
    )


def _crawl_outcome_from_code(
    *,
    code: CrawlOutcomeCode,
    result_location: str | None,
    failure_summary: dict[str, int] | None,
    pages_failed: int | None,
    files_failed: int | None,
    pages_source_retained: int | None,
    pages_hash_retained: int | None,
    files_hash_retained: int | None,
    files_too_large_skipped: int | None,
    processing_summary: CrawlRunProcessingSummary | None,
) -> CrawlOutcomePublic:
    detail = result_location.strip() if result_location else None
    affected_count = (pages_failed or 0) + (files_failed or 0)
    failure_count = sum(failure_summary.values()) if failure_summary else None
    hash_retained_count = (pages_hash_retained or 0) + (files_hash_retained or 0)
    if processing_summary is not None:
        hash_retained_count = (
            processing_summary.pages_hash_retained
            + processing_summary.files_hash_retained
        )
        files_too_large_skipped = processing_summary.files_too_large_skipped

    if code == CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.INFO,
            message_key="crawl_outcome_duplicate_skipped",
            detail=detail,
        )

    if code == CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.WARNING,
            message_key="crawl_outcome_embedding_config_missing",
            affected_count=failure_count or affected_count or None,
        )

    if code == CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.WARNING,
            message_key="crawl_outcome_page_failures",
            affected_count=failure_count or affected_count or None,
        )

    if code == CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.ERROR,
            message_key="crawl_outcome_no_pages_returned",
            detail=detail,
        )

    if code == CrawlOutcomeCode.CRAWL_SITEMAP_NO_PAGES:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.ERROR,
            message_key="crawl_outcome_sitemap_no_pages",
            detail=detail,
        )

    if code == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.ERROR,
            message_key="crawl_outcome_timeout_no_pages",
            detail=detail,
        )

    if code == CrawlOutcomeCode.CRAWL_PARTIAL_TIMEOUT:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.WARNING,
            message_key="crawl_outcome_partial_timeout",
            detail=detail,
        )

    if code == CrawlOutcomeCode.CRAWL_SHUTDOWN_ERROR:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.ERROR,
            message_key="crawl_outcome_shutdown_error",
            detail=detail,
        )

    if code == CrawlOutcomeCode.CRAWL_MAX_AGE_EXCEEDED:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.ERROR,
            message_key="crawl_outcome_max_age_exceeded",
            detail=detail,
        )

    if code == CrawlOutcomeCode.CRAWL_SOURCE_RETENTION_ONLY:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.INFO,
            message_key="crawl_outcome_source_retention_only",
            affected_count=pages_source_retained or None,
        )

    if code == CrawlOutcomeCode.CRAWL_ALL_UNCHANGED:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.INFO,
            message_key="crawl_outcome_all_unchanged",
            affected_count=hash_retained_count or None,
        )

    if code == CrawlOutcomeCode.CRAWL_FILES_TOO_LARGE_ONLY:
        return CrawlOutcomePublic(
            code=code,
            severity=CrawlOutcomeSeverity.WARNING,
            message_key="crawl_outcome_files_too_large_only",
            affected_count=files_too_large_skipped or None,
        )

    return CrawlOutcomePublic(
        code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
        severity=CrawlOutcomeSeverity.ERROR,
        message_key="crawl_outcome_unknown_error",
        detail=detail,
        affected_count=affected_count or None,
    )


class CrawlRunCreate(BaseModel):
    website_id: UUID
    tenant_id: UUID


class CrawlRunUpdate(CrawlRunBase):
    id: UUID
    job_id: Optional[UUID] = None


class CrawlRunSparse(CrawlRunBase, InDB):
    status: Optional[Status] = Field(
        validation_alias=AliasChoices(AliasPath("job", "status"), "status"),
        default=Status.QUEUED,
    )
    result_location: Optional[str] = Field(
        validation_alias=AliasChoices(
            AliasPath("job", "result_location"), "result_location"
        ),
        default=None,
    )
    finished_at: Optional[datetime] = Field(
        validation_alias=AliasChoices(AliasPath("job", "finished_at"), "finished_at"),
        default=None,
    )
    processing_summary: Optional[CrawlRunProcessingSummary] = None
    outcome: Optional[CrawlOutcomePublic] = None

    @model_validator(mode="after")
    def derive_outcome(self) -> Self:
        if self.processing_summary is None:
            self.processing_summary = derive_crawl_processing_summary(
                pages_crawled=self.pages_crawled,
                files_downloaded=self.files_downloaded,
                pages_failed=self.pages_failed,
                files_failed=self.files_failed,
                pages_source_retained=self.pages_source_retained,
                pages_hash_retained=self.pages_hash_retained,
                files_hash_retained=self.files_hash_retained,
                files_too_large_skipped=self.files_too_large_skipped,
            )
        if self.outcome is None:
            self.outcome = derive_crawl_outcome(
                status=self.status,
                result_location=self.result_location,
                failure_summary=self.failure_summary,
                pages_failed=self.pages_failed,
                files_failed=self.files_failed,
                pages_source_retained=self.pages_source_retained,
                pages_hash_retained=self.pages_hash_retained,
                files_hash_retained=self.files_hash_retained,
                files_too_large_skipped=self.files_too_large_skipped,
                processing_summary=self.processing_summary,
                outcome_code=self.outcome_code,
            )
        return self


class CrawlRun(CrawlRunSparse):
    website_id: UUID
    tenant_id: UUID


class CrawlRunPublic(CrawlRunSparse):
    pass
