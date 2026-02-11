from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import AliasChoices, AliasPath, BaseModel, Field

from intric.jobs.task_models import TaskParams
from intric.main.models import InDB, Status
from intric.websites.domain.crawl_run import CrawlType


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
        validation_alias=AliasChoices(AliasPath("job", "result_location"), "result_location"),
        default=None,
    )
    finished_at: Optional[datetime] = Field(
        validation_alias=AliasChoices(AliasPath("job", "finished_at"), "finished_at"),
        default=None,
    )


class CrawlRun(CrawlRunSparse):
    website_id: UUID
    tenant_id: UUID


class CrawlRunPublic(CrawlRunSparse):
    pass
