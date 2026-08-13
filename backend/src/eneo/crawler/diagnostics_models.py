from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from eneo.websites.domain.crawl_run import CrawlType


class CrawlerCapacity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_http_requests_per_process: int
    requests_per_crawl: int
    crawl_jobs_per_tenant: int


class CrawlerLimitsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_pages: int
    max_crawl_seconds: int
    request_timeout_seconds: int
    max_page_bytes: int
    max_file_bytes: int
    retries: int
    obey_robots: bool


class CrawlerWebsiteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str
    url: str
    crawl_type: CrawlType
    requires_http_auth: bool


class CrawlerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Literal["python_async"] = "python_async"
    execution: Literal["in_process"] = "in_process"
    ready: bool = True
    capacity: CrawlerCapacity
    limits: CrawlerLimitsModel
    sitemap_change_detection: bool
    websites: list[CrawlerWebsiteModel]


class CrawlerProbeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    website_id: UUID
    url: str
    crawl_type: CrawlType
    outcome: Literal["reachable", "unchanged", "partial", "failed"]
    duration_ms: int
    pages_crawled: int
    pages_unchanged: int
    pages_failed: int
    sample_title: str | None = None
    reason: str | None = None
    sitemap_snapshot_available: bool = False
