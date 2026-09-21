from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from eneo.jobs.task_models import TaskParams
from eneo.websites.domain.crawl_run import (
    CrawlOrigin,
    CrawlType,
)


class CrawlTask(TaskParams):
    schema_version: Literal[1] = 1
    attempt_id: UUID | None = None
    attempt_number: int | None = Field(default=None, ge=1)
    website_id: UUID
    run_id: UUID
    url: str
    download_files: bool = False
    crawl_type: CrawlType = CrawlType.CRAWL
    origin: CrawlOrigin = CrawlOrigin.MANUAL

    @model_validator(mode="after")
    def validate_attempt_identity(self) -> Self:
        if (self.attempt_id is None) != (self.attempt_number is None):
            raise ValueError("attempt_id and attempt_number must be provided together")
        return self
