from datetime import datetime
from enum import Enum
from typing import Optional, Self
from uuid import UUID

from pydantic import AliasChoices, AliasPath, BaseModel, Field, model_validator

from intric.jobs.task_models import TaskParams
from intric.main.models import InDB, Status
from intric.websites.domain.crawl_run import CrawlType
from intric.worker.crawl_context import FailureReason


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
    failure_summary: Optional[dict[str, int]] = None


class CrawlOutcomeSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class CrawlOutcomeCode(str, Enum):
    CRAWL_DUPLICATE_SKIPPED = "CRAWL_DUPLICATE_SKIPPED"
    CRAWL_NO_PAGES_RETURNED = "CRAWL_NO_PAGES_RETURNED"
    CRAWL_TIMEOUT_NO_PAGES = "CRAWL_TIMEOUT_NO_PAGES"
    CRAWL_COMPLETED_WITH_PAGE_FAILURES = "CRAWL_COMPLETED_WITH_PAGE_FAILURES"
    EMBEDDING_CONFIG_MISSING = "EMBEDDING_CONFIG_MISSING"
    UNKNOWN_CRAWL_ERROR = "UNKNOWN_CRAWL_ERROR"


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
) -> CrawlOutcomePublic | None:
    status_value = status.value if isinstance(status, Status) else status
    detail = result_location.strip() if result_location else None
    detail_lower = detail.lower() if detail else ""
    affected_count = (pages_failed or 0) + (files_failed or 0)

    if status_value == Status.FAILED.value and detail_lower.startswith(
        "skipped duplicate crawl"
    ):
        return CrawlOutcomePublic(
            code=CrawlOutcomeCode.CRAWL_DUPLICATE_SKIPPED,
            severity=CrawlOutcomeSeverity.INFO,
            message_key="crawl_outcome_duplicate_skipped",
            detail=detail,
        )

    if failure_summary:
        failure_count = sum(failure_summary.values())
        if (
            FailureReason.NO_EMBEDDING_MODEL.value in failure_summary
            or FailureReason.MISSING_PROVIDER.value in failure_summary
        ):
            return CrawlOutcomePublic(
                code=CrawlOutcomeCode.EMBEDDING_CONFIG_MISSING,
                severity=CrawlOutcomeSeverity.WARNING,
                message_key="crawl_outcome_embedding_config_missing",
                affected_count=failure_count,
            )

        return CrawlOutcomePublic(
            code=CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
            severity=CrawlOutcomeSeverity.WARNING,
            message_key="crawl_outcome_page_failures",
            affected_count=failure_count,
        )

    if status_value == Status.FAILED.value or status_value == Status.NOT_FOUND.value:
        if "no pages returned" in detail_lower:
            return CrawlOutcomePublic(
                code=CrawlOutcomeCode.CRAWL_NO_PAGES_RETURNED,
                severity=CrawlOutcomeSeverity.ERROR,
                message_key="crawl_outcome_no_pages_returned",
                detail=detail,
            )

        if "timeout" in detail_lower:
            return CrawlOutcomePublic(
                code=CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES,
                severity=CrawlOutcomeSeverity.ERROR,
                message_key="crawl_outcome_timeout_no_pages",
                detail=detail,
            )

        return CrawlOutcomePublic(
            code=CrawlOutcomeCode.UNKNOWN_CRAWL_ERROR,
            severity=CrawlOutcomeSeverity.ERROR,
            message_key="crawl_outcome_unknown_error",
            detail=detail,
            affected_count=affected_count or None,
        )

    if affected_count > 0:
        return CrawlOutcomePublic(
            code=CrawlOutcomeCode.CRAWL_COMPLETED_WITH_PAGE_FAILURES,
            severity=CrawlOutcomeSeverity.WARNING,
            message_key="crawl_outcome_page_failures",
            affected_count=affected_count,
        )

    return None


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
    outcome: Optional[CrawlOutcomePublic] = None

    @model_validator(mode="after")
    def derive_outcome(self) -> Self:
        if self.outcome is None:
            self.outcome = derive_crawl_outcome(
                status=self.status,
                result_location=self.result_location,
                failure_summary=self.failure_summary,
                pages_failed=self.pages_failed,
                files_failed=self.files_failed,
            )
        return self


class CrawlRun(CrawlRunSparse):
    website_id: UUID
    tenant_id: UUID


class CrawlRunPublic(CrawlRunSparse):
    pass
