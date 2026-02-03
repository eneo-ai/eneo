from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator
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


class WebsiteBase(BaseModel):
    name: Optional[str] = None
    url: str
    space_id: Optional[UUID] = None
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL
    update_interval: UpdateInterval = UpdateInterval.NEVER


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


class CrawlRunPublic(BaseResponse):
    pages_crawled: Optional[int]
    files_downloaded: Optional[int]
    pages_failed: Optional[int]
    files_failed: Optional[int]
    failure_summary: Optional[dict[str, int]] = None
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
            failure_summary=crawl_run.failure_summary,
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
    latest_crawl: Optional[CrawlRunPublic]
    embedding_model: EmbeddingModelPublic
    metadata: WebsiteMetadata
    requires_http_auth: bool = Field(
        description="Whether this website requires HTTP Basic Authentication. "
        "Credentials are never exposed via API."
    )
    consecutive_failures: int = Field(
        default=0,
        description="Number of consecutive crawl failures. Resets to 0 on successful crawl.",
    )
    next_retry_at: Optional[datetime] = Field(
        default=None,
        description="When to retry after failures (null = no backoff). "
        "Uses exponential backoff: 1h → 2h → 4h → 8h → 16h → 24h max.",
    )
    is_auto_disabled: bool = Field(
        description="True if website was auto-disabled after 10 consecutive failures. "
        "User must manually change update_interval to re-enable."
    )

    @classmethod
    def from_domain(cls, website: Website):
        latest_crawl = (
            CrawlRunPublic.from_domain(website.latest_crawl)
            if website.latest_crawl
            else None
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
            latest_crawl=latest_crawl,
            embedding_model=EmbeddingModelPublic.from_domain(website.embedding_model),
            metadata=WebsiteMetadata(size=website.size),
            permissions=website.permissions,
            requires_http_auth=website.requires_auth,
            consecutive_failures=website.consecutive_failures,
            next_retry_at=website.next_retry_at,
            is_auto_disabled=website.is_auto_disabled,
        )


class WebsiteCreate(BaseModel):
    name: Optional[str] = None
    url: str
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL
    update_interval: UpdateInterval = UpdateInterval.NEVER
    embedding_model: Optional[ModelId] = None
    """Embedding model to use (defaults to space's default model if not specified)"""

    http_auth_username: Optional[str] = Field(
        None, description="Username for HTTP Basic Authentication (optional)"
    )
    """Username for HTTP Basic Authentication. Required for auth-protected websites."""

    http_auth_password: Optional[str] = Field(
        None,
        description="Password for HTTP Basic Authentication (optional). "
        "Must be provided together with username.",
    )
    """Password for HTTP Basic Authentication. Must be provided with username."""

    @field_validator("http_auth_password")
    @classmethod
    def validate_auth_fields_together(cls, v, info):
        """Ensure username and password are provided together."""
        username = info.data.get("http_auth_username")

        # If one is provided, both must be provided
        if (username and not v) or (v and not username):
            raise ValueError(
                "http_auth_username and http_auth_password must be provided together"
            )

        return v


class WebsiteUpdate(BaseModel):
    url: Union[str, NotProvided] = NOT_PROVIDED
    name: Union[str, None, NotProvided] = NOT_PROVIDED
    download_files: Union[bool, NotProvided] = NOT_PROVIDED
    crawl_type: Union[CrawlType, NotProvided] = NOT_PROVIDED
    update_interval: Union[UpdateInterval, NotProvided] = NOT_PROVIDED

    http_auth_username: Union[str, None, NotProvided] = Field(
        NOT_PROVIDED,
        description="Username for HTTP Basic Authentication. "
        "Set to null to remove auth. Must be provided with password.",
    )
    http_auth_password: Union[str, None, NotProvided] = Field(
        NOT_PROVIDED,
        description="Password for HTTP Basic Authentication. "
        "Set to null to remove auth. Must be provided with username.",
    )

    @field_validator("http_auth_password")
    @classmethod
    def validate_auth_update_together(cls, v, info):
        """Ensure username and password are updated together."""
        username = info.data.get("http_auth_username")

        # Both must be NOT_PROVIDED, both must be None, or both must have values
        if username is NOT_PROVIDED and v is not NOT_PROVIDED:
            raise ValueError("Cannot update password without username")
        if v is NOT_PROVIDED and username is not NOT_PROVIDED:
            raise ValueError("Cannot update username without password")

        # If updating to None (removing auth), both must be None
        if username is None and v is not None:
            raise ValueError("To remove auth, both username and password must be null")
        if v is None and username is not None:
            raise ValueError("To remove auth, both username and password must be null")

        return v


class BulkCrawlRequest(BaseModel):
    """Request model for triggering crawls on multiple websites."""

    website_ids: list[UUID]
    """List of website IDs to crawl (max 50 per request for safety)"""


class BulkCrawlResponse(BaseModel):
    """Response model for bulk crawl operations."""

    total: int
    """Total number of websites requested"""

    queued: int
    """Number of crawls successfully queued"""

    failed: int
    """Number of websites that failed to queue"""

    crawl_runs: list[CrawlRunPublic]
    """Details of successfully queued crawl runs"""

    errors: list[dict[str, str]]
    """List of errors for failed websites (website_id and error message)"""


class WebsiteExistsResponse(BaseModel):
    """Response model for checking if a website URL exists on the Organization space."""

    website_id: UUID
    """ID of the existing website"""

    space_id: UUID
    """ID of the space where the website exists"""

    space_name: str
    """Name of the space where the website exists"""

    url: str
    """URL of the existing website"""

    name: Optional[str]
    """Display name of the existing website"""

    update_interval: UpdateInterval
    """Automatic update interval of the existing website"""

    last_crawled_at: Optional[datetime]
    """When the website was last crawled"""

    pages_crawled: Optional[int] = None
    """Number of pages successfully crawled"""

    pages_failed: Optional[int] = None
    """Number of pages that failed to crawl"""

    files_downloaded: Optional[int] = None
    """Number of files successfully downloaded"""

    files_failed: Optional[int] = None
    """Number of files that failed to download"""

    crawl_status: Optional[str] = None
    """Status of the latest crawl (queued, in progress, complete, failed)"""
