from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional, Union, cast, overload

from typing_extensions import override

from intric.base.base_entity import Entity
from intric.main.models import Status
from intric.websites.domain.crawl_outcome import (
    CrawlOutcomeCode,
    FailureReason,
    parse_crawl_outcome_code_lenient,
    parse_failure_summary_lenient,
    report_legacy_failure_summary_key_dropped,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from intric.database.tables.job_table import Jobs
    from intric.database.tables.websites_table import CrawlRuns as CrawlRunsTable
    from intric.websites.domain.website import Website, WebsiteSparse


class CrawlType(str, Enum):
    CRAWL = "crawl"
    SITEMAP = "sitemap"


MAX_CRAWL_FILE_TOO_LARGE_SAMPLES = 5
MAX_CRAWL_FILE_TOO_LARGE_SAMPLE_URL_CHARS = 2048


def truncate_crawl_file_too_large_sample_url(url: str) -> str:
    return url[:MAX_CRAWL_FILE_TOO_LARGE_SAMPLE_URL_CHARS]


@dataclass(frozen=True, slots=True)
class CrawlFileTooLargeSample:
    """Observed size may be the declared Content-Length when headers stop the download."""

    url: str
    observed_size_bytes: int | None


def parse_crawl_file_too_large_samples(
    value: object,
) -> tuple[CrawlFileTooLargeSample, ...]:
    if not isinstance(value, list):
        return ()

    samples: list[CrawlFileTooLargeSample] = []
    for raw_sample in cast(list[object], value):
        if len(samples) >= MAX_CRAWL_FILE_TOO_LARGE_SAMPLES:
            break
        parsed = _parse_crawl_file_too_large_sample(raw_sample)
        if parsed is not None:
            samples.append(parsed)

    return tuple(samples)


def serialize_crawl_file_too_large_samples(
    samples: Sequence[CrawlFileTooLargeSample],
) -> list[dict[str, int | str | None]] | None:
    serialized = [
        {
            "url": truncate_crawl_file_too_large_sample_url(sample.url),
            "observed_size_bytes": sample.observed_size_bytes,
        }
        for sample in samples[:MAX_CRAWL_FILE_TOO_LARGE_SAMPLES]
    ]
    return serialized or None


def _parse_crawl_file_too_large_sample(
    value: object,
) -> CrawlFileTooLargeSample | None:
    if not isinstance(value, Mapping):
        return None
    sample = cast(Mapping[object, object], value)

    raw_url = sample.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None

    try:
        observed_size_bytes = _optional_non_negative_int(
            sample.get("observed_size_bytes")
        )
    except ValueError:
        return None

    return CrawlFileTooLargeSample(
        url=truncate_crawl_file_too_large_sample_url(raw_url),
        observed_size_bytes=observed_size_bytes,
    )


def _optional_non_negative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected non-negative int or None")
    if value < 0:
        raise ValueError("expected non-negative int or None")
    return value


def _resolved_litellm_model_name(
    *,
    model_name: str | None,
    litellm_model_name: str | None,
    provider_type: str | None,
) -> str | None:
    if model_name and provider_type:
        return f"{provider_type}/{model_name}"
    return litellm_model_name


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
        pages_source_retained: Optional[int],
        pages_hash_retained: Optional[int],
        files_hash_retained: Optional[int],
        files_too_large_skipped: Optional[int],
        status: Status,
        result_location: Optional[str],
        finished_at: Optional["datetime"],
        job_id: Optional["UUID"],
        failure_summary: Optional[dict[FailureReason, int]] = None,
        outcome_code: Optional[CrawlOutcomeCode] = None,
        files_too_large_download_limit_bytes: Optional[int] = None,
        files_too_large_samples: tuple[CrawlFileTooLargeSample, ...] = (),
        embedding_model_id: Optional["UUID"] = None,
        embedding_model_name_snapshot: Optional[str] = None,
        embedding_model_litellm_name_snapshot: Optional[str] = None,
        embedding_model_provider_snapshot: Optional[str] = None,
        embedding_input_cost_per_token_snapshot: Optional[Decimal] = None,
        embedding_input_tokens: Optional[int] = None,
        embedding_usage_source: Optional[str] = None,
        embedding_total_cost_usd: Optional[Decimal] = None,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.status = status
        self.result_location = result_location
        self.pages_crawled = pages_crawled
        self.files_downloaded = files_downloaded
        self.pages_failed = pages_failed
        self.files_failed = files_failed
        self.pages_source_retained = pages_source_retained
        self.pages_hash_retained = pages_hash_retained
        self.files_hash_retained = files_hash_retained
        self.files_too_large_skipped = files_too_large_skipped
        self.files_too_large_download_limit_bytes = files_too_large_download_limit_bytes
        self.files_too_large_samples = files_too_large_samples
        self.finished_at = finished_at
        self.website_id = website_id
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.failure_summary = failure_summary
        self.outcome_code = outcome_code
        self.embedding_model_id = embedding_model_id
        self.embedding_model_name_snapshot = embedding_model_name_snapshot
        self.embedding_model_litellm_name_snapshot = (
            embedding_model_litellm_name_snapshot
        )
        self.embedding_model_provider_snapshot = embedding_model_provider_snapshot
        self.embedding_input_cost_per_token_snapshot = (
            embedding_input_cost_per_token_snapshot
        )
        self.embedding_input_tokens = embedding_input_tokens
        self.embedding_usage_source = embedding_usage_source
        self.embedding_total_cost_usd = embedding_total_cost_usd

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
        embedding_model = getattr(website, "embedding_model", None)
        if embedding_model is not None:
            embedding_model_id = getattr(embedding_model, "id", None)
            embedding_model_name = getattr(embedding_model, "name", None)
            embedding_model_provider = getattr(embedding_model, "provider_type", None)
            embedding_model_litellm_name = _resolved_litellm_model_name(
                model_name=embedding_model_name,
                litellm_model_name=getattr(embedding_model, "litellm_model_name", None),
                provider_type=embedding_model_provider,
            )
            input_cost_per_token = getattr(
                embedding_model, "input_cost_per_token", None
            )
        else:
            embedding_model_id = getattr(website, "embedding_model_id", None)
            embedding_model_name = getattr(website, "embedding_model_name", None)
            embedding_model_provider = getattr(
                website, "embedding_model_provider_type", None
            )
            embedding_model_litellm_name = _resolved_litellm_model_name(
                model_name=embedding_model_name,
                litellm_model_name=getattr(
                    website, "embedding_model_litellm_name", None
                ),
                provider_type=embedding_model_provider,
            )
            input_cost_per_token = getattr(
                website, "embedding_model_input_cost_per_token", None
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
            pages_source_retained=None,
            pages_hash_retained=None,
            files_hash_retained=None,
            files_too_large_skipped=None,
            files_too_large_download_limit_bytes=None,
            files_too_large_samples=(),
            status=Status.QUEUED,
            result_location=None,
            finished_at=None,
            job_id=None,
            failure_summary=None,
            outcome_code=None,
            embedding_model_id=embedding_model_id,
            embedding_model_name_snapshot=embedding_model_name,
            embedding_model_litellm_name_snapshot=embedding_model_litellm_name,
            embedding_model_provider_snapshot=embedding_model_provider,
            embedding_input_cost_per_token_snapshot=input_cost_per_token,
            embedding_input_tokens=0 if embedding_model_id is not None else None,
            embedding_usage_source=None,
            embedding_total_cost_usd=(
                Decimal("0") if input_cost_per_token is not None else None
            ),
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
            pages_source_retained=record.pages_source_retained,
            pages_hash_retained=record.pages_hash_retained,
            files_hash_retained=record.files_hash_retained,
            files_too_large_skipped=record.files_too_large_skipped,
            files_too_large_download_limit_bytes=(
                record.files_too_large_download_limit_bytes
            ),
            files_too_large_samples=parse_crawl_file_too_large_samples(
                record.files_too_large_samples
            ),
            job_id=record.job_id,
            status=Status(job.status) if job else Status.QUEUED,
            result_location=job.result_location if job else None,
            finished_at=job.finished_at if job else None,
            failure_summary=parse_failure_summary_lenient(
                record.failure_summary,
                on_unknown_key=report_legacy_failure_summary_key_dropped,
            ),
            outcome_code=parse_crawl_outcome_code_lenient(record.outcome_code),
            embedding_model_id=record.embedding_model_id,
            embedding_model_name_snapshot=record.embedding_model_name_snapshot,
            embedding_model_litellm_name_snapshot=(
                record.embedding_model_litellm_name_snapshot
            ),
            embedding_model_provider_snapshot=record.embedding_model_provider_snapshot,
            embedding_input_cost_per_token_snapshot=(
                record.embedding_input_cost_per_token_snapshot
            ),
            embedding_input_tokens=record.embedding_input_tokens,
            embedding_usage_source=record.embedding_usage_source,
            embedding_total_cost_usd=record.embedding_total_cost_usd,
        )

    def update(
        self,
        job_id: Optional["UUID"] = None,
        pages_crawled: Optional[int] = None,
        files_downloaded: Optional[int] = None,
        pages_failed: Optional[int] = None,
        files_failed: Optional[int] = None,
        pages_source_retained: Optional[int] = None,
        pages_hash_retained: Optional[int] = None,
        files_hash_retained: Optional[int] = None,
        files_too_large_skipped: Optional[int] = None,
        outcome_code: Optional[CrawlOutcomeCode] = None,
        files_too_large_download_limit_bytes: Optional[int] = None,
        files_too_large_samples: Sequence[CrawlFileTooLargeSample] | None = None,
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

        if pages_source_retained is not None:
            self.pages_source_retained = pages_source_retained

        if pages_hash_retained is not None:
            self.pages_hash_retained = pages_hash_retained

        if files_hash_retained is not None:
            self.files_hash_retained = files_hash_retained

        if files_too_large_skipped is not None:
            self.files_too_large_skipped = files_too_large_skipped

        if files_too_large_download_limit_bytes is not None:
            self.files_too_large_download_limit_bytes = (
                files_too_large_download_limit_bytes
            )

        if files_too_large_samples is not None:
            self.files_too_large_samples = tuple(files_too_large_samples)

        if outcome_code is not None:
            self.outcome_code = outcome_code

        return self
