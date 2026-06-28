from enum import Enum
from typing import TYPE_CHECKING, Optional, Union, cast, overload

from typing_extensions import override

from eneo.base.base_entity import Entity
from eneo.main.models import Status

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from eneo.database.tables.job_table import Jobs
    from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
    from eneo.websites.domain.website import Website, WebsiteSparse


class CrawlType(str, Enum):
    CRAWL = "crawl"
    SITEMAP = "sitemap"


class CrawlRun(Entity):
    def __init__(
        self,
        id: Optional["UUID"],
        created_at: Optional["datetime"],
        updated_at: Optional["datetime"],
        website_id: "UUID",
        tenant_id: "UUID",
        pages_crawled: Optional[int],
        files_downloaded: Optional[int],
        pages_failed: Optional[int],
        files_failed: Optional[int],
        status: Status,
        result_location: Optional[str],
        finished_at: Optional["datetime"],
        job_id: Optional["UUID"],
        failure_summary: Optional[dict[str, int]] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.status = status
        self.result_location = result_location
        self.pages_crawled = pages_crawled
        self.files_downloaded = files_downloaded
        self.pages_failed = pages_failed
        self.files_failed = files_failed
        self.finished_at = finished_at
        self.website_id = website_id
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.failure_summary = failure_summary

    @overload
    @classmethod
    def create(cls, website: Union["Website", "WebsiteSparse"], /) -> "CrawlRun": ...

    @overload
    @classmethod
    def create(cls, *, website: Union["Website", "WebsiteSparse"]) -> "CrawlRun": ...

    @override
    @classmethod
    def create(cls, *args: object, **kwargs: object) -> "CrawlRun":
        website = (
            cast(Union["Website", "WebsiteSparse"], args[0])
            if args
            else cast(Union["Website", "WebsiteSparse"], kwargs["website"])
        )
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
            status=Status.QUEUED,
            result_location=None,
            finished_at=None,
            job_id=None,
            failure_summary=None,
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
        job = cast("Jobs | None", getattr(record, "job", None))

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
            status=Status(job.status) if job else Status.QUEUED,
            result_location=job.result_location if job else None,
            finished_at=job.finished_at if job else None,
            failure_summary=record.failure_summary,
        )

    def update(
        self,
        job_id: Optional["UUID"] = None,
        pages_crawled: Optional[int] = None,
        files_downloaded: Optional[int] = None,
        pages_failed: Optional[int] = None,
        files_failed: Optional[int] = None,
    ) -> "CrawlRun":
        if job_id is not None:
            self.job_id = job_id

        if pages_crawled is not None:
            self.pages_crawled = pages_crawled

        if files_downloaded is not None:
            self.files_downloaded = files_downloaded

        if pages_failed is not None:
            self.pages_failed = pages_failed

        if files_failed is not None:
            self.files_failed = files_failed

        return self
