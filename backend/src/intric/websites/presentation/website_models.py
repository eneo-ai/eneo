from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, field_serializer
from pydantic.networks import HttpUrl

from intric.embedding_models.presentation.embedding_model_models import (
    EmbeddingModelPublic,
)
from intric.main.models import (
    NOT_PROVIDED,
    BaseResponse,
    IdAndName,
    InDB,
    ModelId,
    NotProvided,
    ResourcePermissionsMixin,
    Status,
)
from intric.websites.crawl_dependencies.crawl_models import CrawlRunSparse
from intric.websites.domain.crawl_run import CrawlRun, CrawlType
from intric.websites.domain.website import UpdateInterval, Website
from intric.websites.domain.crawler_engine import CrawlerEngine


class WebsiteBase(BaseModel):
    name: Optional[str] = None
    url: str
    space_id: Optional[UUID] = None
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL
    update_interval: UpdateInterval = UpdateInterval.NEVER
    crawler_engine: CrawlerEngine = CrawlerEngine.SCRAPY


class WebsiteCreateRequestDeprecated(WebsiteBase):
    url: HttpUrl
    embedding_model: ModelId

    @field_serializer("url")
    def serialize_to_string(url: HttpUrl):
        return str(url)


class WebsiteInDBBase(InDB):
    space_id: Optional[UUID] = None
    embedding_model_id: Optional[UUID] = None
    user_id: UUID
    tenant_id: UUID
    embedding_model_id: UUID
    size: int = 0


class WebsiteMetadata(BaseModel):
    size: int


class WebsiteSparse(ResourcePermissionsMixin, WebsiteBase, InDB):
    url: str
    latest_crawl: Optional[CrawlRunSparse] = None
    user_id: UUID
    embedding_model: IdAndName
    metadata: WebsiteMetadata
    crawler_engine: CrawlerEngine


class CrawlRunPublic(BaseResponse):
    pages_crawled: Optional[int]
    files_downloaded: Optional[int]
    pages_failed: Optional[int]
    files_failed: Optional[int]
    status: Status
    result_location: Optional[str]
    finished_at: Optional[datetime]

    @classmethod
    def from_domain(cls, crawl_run: CrawlRun):
        return cls(
            id=crawl_run.id,
            created_at=crawl_run.created_at,
            updated_at=crawl_run.updated_at,
            pages_crawled=crawl_run.pages_crawled,
            files_downloaded=crawl_run.files_downloaded,
            pages_failed=crawl_run.pages_failed,
            files_failed=crawl_run.files_failed,
            status=crawl_run.status,
            result_location=crawl_run.result_location,
            finished_at=crawl_run.finished_at,
        )


class WebsitePublic(ResourcePermissionsMixin, BaseResponse):
    name: Optional[str]
    url: str
    space_id: UUID
    download_files: bool
    crawl_type: CrawlType
    update_interval: UpdateInterval
    crawler_engine: CrawlerEngine
    latest_crawl: Optional[CrawlRunPublic]
    embedding_model: EmbeddingModelPublic
    metadata: WebsiteMetadata

    @classmethod
    def from_domain(cls, website: Website):
        latest_crawl = (
            CrawlRunPublic.from_domain(website.latest_crawl) if website.latest_crawl else None
        )

        return cls(
            id=website.id,
            created_at=website.created_at,
            updated_at=website.updated_at,
            name=website.name,
            url=website.url,
            space_id=website.space_id,
            download_files=website.download_files,
            crawl_type=website.crawl_type,
            update_interval=website.update_interval,
            crawler_engine=website.crawler_engine,
            latest_crawl=latest_crawl,
            embedding_model=EmbeddingModelPublic.from_domain(website.embedding_model),
            metadata=WebsiteMetadata(size=website.size),
            permissions=website.permissions,
        )


class WebsiteCreate(BaseModel):
    name: Optional[str] = None
    url: str
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL
    update_interval: UpdateInterval = UpdateInterval.NEVER
    embedding_model: Optional[ModelId] = None
    crawler_engine: CrawlerEngine = CrawlerEngine.SCRAPY


class WebsiteUpdate(BaseModel):
    url: Union[str, NotProvided] = NOT_PROVIDED
    name: Union[str, None, NotProvided] = NOT_PROVIDED
    download_files: Union[bool, NotProvided] = NOT_PROVIDED
    crawl_type: Union[CrawlType, NotProvided] = NOT_PROVIDED
    update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED
    crawler_engine: Union[CrawlerEngine, NotProvided] = NOT_PROVIDED
