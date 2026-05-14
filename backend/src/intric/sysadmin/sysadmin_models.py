from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from intric.main.models import ModelId
from intric.spaces.api.space_models import AddSpaceMemberRequest
from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
from intric.websites.domain.crawler_baseline import (
    CrawlerBaselineMetrics as DomainCrawlerBaselineMetrics,
)
from intric.websites.domain.crawler_baseline import (
    CrawlerBaselineProcessingTotals as DomainCrawlerBaselineProcessingTotals,
)
from intric.websites.domain.crawler_baseline import (
    CrawlOutcomeBucket as DomainCrawlOutcomeBucket,
)


def _empty_model_id_list() -> list[ModelId]:
    return []


def _empty_member_list() -> list[AddSpaceMemberRequest]:
    return []


class InfoBlobDifference(BaseModel):
    database_ids: set[str]
    datastore_ids: set[str]
    database_difference: set[str]
    datastore_difference: set[str]


class ExtraBlobs(BaseModel):
    count: int
    ids: list[str]


class AggregatedExtraBlobs(BaseModel):
    database: ExtraBlobs
    datastore: ExtraBlobs


class InfoBlobDifferencePublic(BaseModel):
    database_count: int
    datastore_count: int
    extra_info_blobs: AggregatedExtraBlobs


class CreateAndImportSpaceRequest(BaseModel):
    name: str
    embedding_model: ModelId
    assistants: list[ModelId] = Field(default_factory=_empty_model_id_list)
    groups: list[ModelId] = Field(default_factory=_empty_model_id_list)
    websites: list[ModelId] = Field(default_factory=_empty_model_id_list)
    members: list[AddSpaceMemberRequest] = Field(default_factory=_empty_member_list)


class CrawlOutcomeBucket(BaseModel):
    code: CrawlOutcomeCode
    count: int = Field(
        ge=0,
        description="Terminal crawl runs with this strict typed outcome code.",
    )

    @classmethod
    def from_domain(cls, bucket: DomainCrawlOutcomeBucket) -> "CrawlOutcomeBucket":
        return cls(code=bucket.code, count=bucket.count)


class CrawlerBaselineProcessingTotals(BaseModel):
    pages_crawled: int = Field(ge=0)
    files_downloaded: int = Field(ge=0)
    pages_hash_retained: int = Field(ge=0)
    files_hash_retained: int = Field(ge=0)
    pages_source_retained: int = Field(ge=0)
    files_too_large_skipped: int = Field(ge=0)
    pages_failed: int = Field(ge=0)
    files_failed: int = Field(ge=0)

    @classmethod
    def from_domain(
        cls, totals: DomainCrawlerBaselineProcessingTotals
    ) -> "CrawlerBaselineProcessingTotals":
        return cls(
            pages_crawled=totals.pages_crawled,
            files_downloaded=totals.files_downloaded,
            pages_hash_retained=totals.pages_hash_retained,
            files_hash_retained=totals.files_hash_retained,
            pages_source_retained=totals.pages_source_retained,
            files_too_large_skipped=totals.files_too_large_skipped,
            pages_failed=totals.pages_failed,
            files_failed=totals.files_failed,
        )


class CrawlerBaselineResponse(BaseModel):
    window_days: int = Field(ge=1, le=30)
    since: datetime
    until: datetime
    tenant_id: UUID | None
    total_runs: int = Field(ge=0)
    terminal_runs: int = Field(ge=0)
    failed_runs: int = Field(ge=0)
    failed_runs_without_typed_outcome: int = Field(ge=0)
    typed_failed_runs: int = Field(ge=0)
    typed_unknown_failed_runs: int = Field(ge=0)
    typed_unknown_failed_rate_percent: float = Field(ge=0)
    legacy_null_outcome_runs: int = Field(
        ge=0,
        description="Terminal crawl runs that still have no typed outcome code.",
    )
    unparseable_outcome_runs: int = Field(
        ge=0,
        description=(
            "Terminal crawl runs with an outcome code that is not in the current "
            "closed enum."
        ),
    )
    outcome_counts: list[CrawlOutcomeBucket] = Field(
        description="Terminal crawl runs grouped by strict typed outcome code."
    )
    processing_totals: CrawlerBaselineProcessingTotals

    @classmethod
    def from_domain(
        cls, metrics: DomainCrawlerBaselineMetrics
    ) -> "CrawlerBaselineResponse":
        return cls(
            window_days=metrics.window_days,
            since=metrics.since,
            until=metrics.until,
            tenant_id=metrics.tenant_id,
            total_runs=metrics.total_runs,
            terminal_runs=metrics.terminal_runs,
            failed_runs=metrics.failed_runs,
            failed_runs_without_typed_outcome=(
                metrics.failed_runs_without_typed_outcome
            ),
            typed_failed_runs=metrics.typed_failed_runs,
            typed_unknown_failed_runs=metrics.typed_unknown_failed_runs,
            typed_unknown_failed_rate_percent=(
                metrics.typed_unknown_failed_rate_percent
            ),
            legacy_null_outcome_runs=metrics.legacy_null_outcome_runs,
            unparseable_outcome_runs=metrics.unparseable_outcome_runs,
            outcome_counts=[
                CrawlOutcomeBucket.from_domain(bucket)
                for bucket in metrics.outcome_counts
            ],
            processing_totals=CrawlerBaselineProcessingTotals.from_domain(
                metrics.processing_totals
            ),
        )
