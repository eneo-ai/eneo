from datetime import datetime
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Optional, Union, cast, overload

from typing_extensions import override

from eneo.base.base_entity import Entity
from eneo.main.models import Status

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
    from eneo.websites.domain.website import Website, WebsiteSparse


class CrawlType(str, Enum):
    CRAWL = "crawl"
    SITEMAP = "sitemap"


class CrawlOrigin(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    LEGACY = "legacy"


class CrawlPhase(StrEnum):
    PENDING_DISPATCH = "pending_dispatch"
    QUEUED = "queued"
    RUNNING = "running"
    FINALIZING = "finalizing"
    STOPPING = "stopping"
    TERMINAL = "terminal"


class CrawlOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    UNCHANGED = "unchanged"
    EMPTY = "empty"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class CrawlFailureCode(StrEnum):
    DISPATCH_FAILED = "dispatch_failed"
    INVALID_DISPATCH = "invalid_dispatch"
    WORKER_INTERRUPTED = "worker_interrupted"
    LEASE_EXPIRED = "lease_expired"
    REMOTE_UNREACHABLE = "remote_unreachable"
    REMOTE_BLOCKED = "remote_blocked"
    TIMED_OUT = "timed_out"
    PROCESSING_FAILED = "processing_failed"
    CANCELLED = "cancelled"


_SUCCESSFUL_OUTCOMES = {
    CrawlOutcome.SUCCEEDED,
    CrawlOutcome.UNCHANGED,
    CrawlOutcome.EMPTY,
    CrawlOutcome.PARTIAL,
}


def project_crawl_status(
    phase: CrawlPhase | str,
    outcome: CrawlOutcome | str | None,
) -> Status:
    """Project the legacy API status without consulting the transport job."""
    crawl_phase = CrawlPhase(phase)
    crawl_outcome = CrawlOutcome(outcome) if outcome is not None else None
    if crawl_phase in {CrawlPhase.PENDING_DISPATCH, CrawlPhase.QUEUED}:
        return Status.QUEUED
    if crawl_phase in {
        CrawlPhase.RUNNING,
        CrawlPhase.FINALIZING,
        CrawlPhase.STOPPING,
    }:
        return Status.IN_PROGRESS
    if crawl_outcome in _SUCCESSFUL_OUTCOMES:
        return Status.COMPLETE
    return Status.FAILED


class CrawlRun(Entity):
    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional[datetime],
        updated_at: Optional[datetime],
        website_id: "UUID",
        tenant_id: "UUID",
        pages_crawled: Optional[int],
        files_downloaded: Optional[int],
        pages_failed: Optional[int],
        files_failed: Optional[int],
        phase: CrawlPhase,
        outcome: Optional[CrawlOutcome],
        origin: CrawlOrigin,
        result_location: Optional[str],
        finished_at: Optional[datetime],
        job_id: Optional["UUID"],
        attempt_count: int,
        failure_code: Optional[str] = None,
        failure_detail: Optional[str] = None,
        cancel_requested_at: Optional[datetime] = None,
        failure_summary: Optional[dict[str, int]] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.website_id = website_id
        self.tenant_id = tenant_id
        self.pages_crawled = pages_crawled
        self.files_downloaded = files_downloaded
        self.pages_failed = pages_failed
        self.files_failed = files_failed
        self.phase = phase
        self.outcome = outcome
        self.origin = origin
        self.result_location = result_location
        self.finished_at = finished_at
        self.job_id = job_id
        self.attempt_count = attempt_count
        self.failure_code = failure_code
        self.failure_detail = failure_detail
        self.cancel_requested_at = cancel_requested_at
        self.failure_summary = failure_summary

    @property
    def status(self) -> Status:
        """Project the legacy API status from the authoritative lifecycle."""
        return project_crawl_status(self.phase, self.outcome)

    @overload
    @classmethod
    def create(
        cls,
        website: Union["Website", "WebsiteSparse"],
        /,
        *,
        origin: CrawlOrigin = CrawlOrigin.MANUAL,
    ) -> "CrawlRun": ...

    @overload
    @classmethod
    def create(
        cls,
        *,
        website: Union["Website", "WebsiteSparse"],
        origin: CrawlOrigin = CrawlOrigin.MANUAL,
    ) -> "CrawlRun": ...

    @override
    @classmethod
    def create(cls, *args: object, **kwargs: object) -> "CrawlRun":
        website = (
            cast(Union["Website", "WebsiteSparse"], args[0])
            if args
            else cast(Union["Website", "WebsiteSparse"], kwargs["website"])
        )
        origin = CrawlOrigin(cast(str, kwargs.get("origin", CrawlOrigin.MANUAL)))
        return cls(
            id=None,
            created_at=None,
            updated_at=None,
            website_id=website.id,
            tenant_id=website.tenant_id,
            pages_crawled=None,
            files_downloaded=None,
            pages_failed=None,
            files_failed=None,
            phase=CrawlPhase.PENDING_DISPATCH,
            outcome=None,
            origin=origin,
            result_location=None,
            finished_at=None,
            job_id=None,
            attempt_count=0,
        )

    @classmethod
    @overload
    def to_domain(cls, db_model: "CrawlRunsTable") -> "CrawlRun": ...

    @overload
    @classmethod
    def to_domain(
        cls,
        *,
        record: "CrawlRunsTable",
    ) -> "CrawlRun": ...

    @override
    @classmethod
    def to_domain(
        cls,
        db_model: object = None,
        *args: object,
        **kwargs: object,
    ) -> "CrawlRun":
        del args
        record = cast(
            "CrawlRunsTable",
            db_model if db_model is not None else kwargs["record"],
        )
        return cls(
            id=record.id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            website_id=record.website_id,
            tenant_id=record.tenant_id,
            pages_crawled=record.pages_crawled,
            files_downloaded=record.files_downloaded,
            pages_failed=record.pages_failed,
            files_failed=record.files_failed,
            job_id=record.job_id,
            phase=CrawlPhase(record.phase),
            outcome=CrawlOutcome(record.outcome) if record.outcome else None,
            origin=CrawlOrigin(record.origin),
            result_location=record.result_location,
            finished_at=record.finished_at,
            attempt_count=record.attempt_count,
            failure_code=record.failure_code,
            failure_detail=record.failure_detail,
            cancel_requested_at=record.cancel_requested_at,
            failure_summary=record.failure_summary,
        )
