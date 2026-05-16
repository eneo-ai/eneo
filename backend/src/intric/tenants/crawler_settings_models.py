from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from intric.tenants.crawler_settings_helper import (
    CRAWLER_SETTING_SPECS,
    SELF_SERVICE_CRAWLER_SETTING_KEYS,
    get_crawler_setting_specs,
)

_SPECS = CRAWLER_SETTING_SPECS


class EffectiveCrawlerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawl_max_length: int = Field(
        ..., description=_SPECS["crawl_max_length"].description
    )
    download_timeout: int = Field(
        ..., description=_SPECS["download_timeout"].description
    )
    download_max_size: int = Field(
        ..., description=_SPECS["download_max_size"].description
    )
    dns_timeout: int = Field(..., description=_SPECS["dns_timeout"].description)
    retry_times: int = Field(..., description=_SPECS["retry_times"].description)
    closespider_itemcount: int = Field(
        ..., description=_SPECS["closespider_itemcount"].description
    )
    obey_robots: bool = Field(..., description=_SPECS["obey_robots"].description)
    autothrottle_enabled: bool = Field(
        ..., description=_SPECS["autothrottle_enabled"].description
    )
    tenant_worker_concurrency_limit: int = Field(
        ..., description=_SPECS["tenant_worker_concurrency_limit"].description
    )
    crawl_stale_threshold_minutes: int = Field(
        ..., description=_SPECS["crawl_stale_threshold_minutes"].description
    )
    queued_stale_threshold_minutes: int = Field(
        ..., description=_SPECS["queued_stale_threshold_minutes"].description
    )
    crawl_heartbeat_interval_seconds: int = Field(
        ..., description=_SPECS["crawl_heartbeat_interval_seconds"].description
    )
    crawl_feeder_enabled: bool = Field(
        ..., description=_SPECS["crawl_feeder_enabled"].description
    )
    crawl_feeder_interval_seconds: int = Field(
        ..., description=_SPECS["crawl_feeder_interval_seconds"].description
    )
    crawl_feeder_batch_size: int = Field(
        ..., description=_SPECS["crawl_feeder_batch_size"].description
    )
    crawl_job_max_age_seconds: int = Field(
        ..., description=_SPECS["crawl_job_max_age_seconds"].description
    )
    tenant_worker_semaphore_ttl_seconds: int = Field(
        ..., description=_SPECS["tenant_worker_semaphore_ttl_seconds"].description
    )
    crawl_page_batch_size: int = Field(
        ..., description=_SPECS["crawl_page_batch_size"].description
    )
    crawl_sitemap_lastmod_skip_enabled: bool = Field(
        ..., description=_SPECS["crawl_sitemap_lastmod_skip_enabled"].description
    )


class CrawlerSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawl_max_length: int | None = Field(
        None,
        ge=_SPECS["crawl_max_length"].min,
        le=_SPECS["crawl_max_length"].max,
        description=_SPECS["crawl_max_length"].description,
    )
    download_timeout: int | None = Field(
        None,
        ge=_SPECS["download_timeout"].min,
        le=_SPECS["download_timeout"].max,
        description=_SPECS["download_timeout"].description,
    )
    download_max_size: int | None = Field(
        None,
        ge=_SPECS["download_max_size"].min,
        le=_SPECS["download_max_size"].max,
        description=_SPECS["download_max_size"].description,
    )
    dns_timeout: int | None = Field(
        None,
        ge=_SPECS["dns_timeout"].min,
        le=_SPECS["dns_timeout"].max,
        description=_SPECS["dns_timeout"].description,
    )
    retry_times: int | None = Field(
        None,
        ge=_SPECS["retry_times"].min,
        le=_SPECS["retry_times"].max,
        description=_SPECS["retry_times"].description,
    )
    closespider_itemcount: int | None = Field(
        None,
        ge=_SPECS["closespider_itemcount"].min,
        le=_SPECS["closespider_itemcount"].max,
        description=_SPECS["closespider_itemcount"].description,
    )
    obey_robots: bool | None = Field(
        None,
        description=_SPECS["obey_robots"].description,
    )
    autothrottle_enabled: bool | None = Field(
        None,
        description=_SPECS["autothrottle_enabled"].description,
    )
    tenant_worker_concurrency_limit: int | None = Field(
        None,
        ge=_SPECS["tenant_worker_concurrency_limit"].min,
        le=_SPECS["tenant_worker_concurrency_limit"].max,
        description=_SPECS["tenant_worker_concurrency_limit"].description,
    )
    crawl_stale_threshold_minutes: int | None = Field(
        None,
        ge=_SPECS["crawl_stale_threshold_minutes"].min,
        le=_SPECS["crawl_stale_threshold_minutes"].max,
        description=_SPECS["crawl_stale_threshold_minutes"].description,
    )
    queued_stale_threshold_minutes: int | None = Field(
        None,
        ge=_SPECS["queued_stale_threshold_minutes"].min,
        le=_SPECS["queued_stale_threshold_minutes"].max,
        description=_SPECS["queued_stale_threshold_minutes"].description,
    )
    crawl_heartbeat_interval_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_heartbeat_interval_seconds"].min,
        le=_SPECS["crawl_heartbeat_interval_seconds"].max,
        description=_SPECS["crawl_heartbeat_interval_seconds"].description,
    )
    crawl_feeder_enabled: bool | None = Field(
        None,
        description=_SPECS["crawl_feeder_enabled"].description,
    )
    crawl_feeder_interval_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_feeder_interval_seconds"].min,
        le=_SPECS["crawl_feeder_interval_seconds"].max,
        description=_SPECS["crawl_feeder_interval_seconds"].description,
    )
    crawl_feeder_batch_size: int | None = Field(
        None,
        ge=_SPECS["crawl_feeder_batch_size"].min,
        le=_SPECS["crawl_feeder_batch_size"].max,
        description=_SPECS["crawl_feeder_batch_size"].description,
    )
    crawl_job_max_age_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_job_max_age_seconds"].min,
        le=_SPECS["crawl_job_max_age_seconds"].max,
        description=_SPECS["crawl_job_max_age_seconds"].description,
    )
    tenant_worker_semaphore_ttl_seconds: int | None = Field(
        None,
        ge=_SPECS["tenant_worker_semaphore_ttl_seconds"].min,
        le=_SPECS["tenant_worker_semaphore_ttl_seconds"].max,
        description=_SPECS["tenant_worker_semaphore_ttl_seconds"].description,
    )
    crawl_page_batch_size: int | None = Field(
        None,
        ge=_SPECS["crawl_page_batch_size"].min,
        le=_SPECS["crawl_page_batch_size"].max,
        description=_SPECS["crawl_page_batch_size"].description,
    )
    crawl_sitemap_lastmod_skip_enabled: bool | None = Field(
        None,
        description=_SPECS["crawl_sitemap_lastmod_skip_enabled"].description,
    )


class CrawlerSettingsSelfServiceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crawl_sitemap_lastmod_skip_enabled: bool | None = Field(
        None,
        description=_SPECS["crawl_sitemap_lastmod_skip_enabled"].description,
    )
    obey_robots: bool | None = Field(
        None,
        description=_SPECS["obey_robots"].description,
    )
    autothrottle_enabled: bool | None = Field(
        None,
        description=_SPECS["autothrottle_enabled"].description,
    )
    download_max_size: int | None = Field(
        None,
        ge=_SPECS["download_max_size"].min,
        le=_SPECS["download_max_size"].max,
        description=_SPECS["download_max_size"].description,
    )
    download_timeout: int | None = Field(
        None,
        ge=_SPECS["download_timeout"].min,
        le=_SPECS["download_timeout"].max,
        description=_SPECS["download_timeout"].description,
    )
    dns_timeout: int | None = Field(
        None,
        ge=_SPECS["dns_timeout"].min,
        le=_SPECS["dns_timeout"].max,
        description=_SPECS["dns_timeout"].description,
    )
    retry_times: int | None = Field(
        None,
        ge=_SPECS["retry_times"].min,
        le=_SPECS["retry_times"].max,
        description=_SPECS["retry_times"].description,
    )
    closespider_itemcount: int | None = Field(
        None,
        ge=_SPECS["closespider_itemcount"].min,
        le=_SPECS["closespider_itemcount"].max,
        description=_SPECS["closespider_itemcount"].description,
    )
    # Tenant-scoped runtime knobs exposed in sub-tranche 3a. Values are read
    # at crawl start, so a tenant-admin change does not affect already-running
    # crawls; each new crawl picks up the updated value. Bounds match the
    # canonical CrawlerSettingSpec definitions so the same min/max protects
    # the API boundary and the worker runtime.
    crawl_max_length: int | None = Field(
        None,
        ge=_SPECS["crawl_max_length"].min,
        le=_SPECS["crawl_max_length"].max,
        description=_SPECS["crawl_max_length"].description,
    )
    crawl_stale_threshold_minutes: int | None = Field(
        None,
        ge=_SPECS["crawl_stale_threshold_minutes"].min,
        le=_SPECS["crawl_stale_threshold_minutes"].max,
        description=_SPECS["crawl_stale_threshold_minutes"].description,
    )
    queued_stale_threshold_minutes: int | None = Field(
        None,
        ge=_SPECS["queued_stale_threshold_minutes"].min,
        le=_SPECS["queued_stale_threshold_minutes"].max,
        description=_SPECS["queued_stale_threshold_minutes"].description,
    )
    crawl_heartbeat_interval_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_heartbeat_interval_seconds"].min,
        le=_SPECS["crawl_heartbeat_interval_seconds"].max,
        description=_SPECS["crawl_heartbeat_interval_seconds"].description,
    )
    crawl_job_max_age_seconds: int | None = Field(
        None,
        ge=_SPECS["crawl_job_max_age_seconds"].min,
        le=_SPECS["crawl_job_max_age_seconds"].max,
        description=_SPECS["crawl_job_max_age_seconds"].description,
    )


class CrawlerSettingSpecPublic(BaseModel):
    type: Literal["int", "bool"] = Field(..., description="Crawler setting value type")
    description: str = Field(..., description="Backend description of the setting")
    min: int | None = Field(None, description="Minimum allowed integer value")
    max: int | None = Field(None, description="Maximum allowed integer value")


def _self_service_setting_specs() -> dict[str, CrawlerSettingSpecPublic]:
    return {
        key: CrawlerSettingSpecPublic.model_validate(value)
        for key, value in get_crawler_setting_specs(
            sorted(SELF_SERVICE_CRAWLER_SETTING_KEYS)
        ).items()
    }


class CrawlerSettingsResponse(BaseModel):
    tenant_id: UUID = Field(..., description="Tenant UUID")
    settings: EffectiveCrawlerSettings = Field(
        ..., description="Current effective crawler settings"
    )
    overrides: list[str] = Field(
        ..., description="Setting keys that have tenant-specific overrides"
    )
    updated_at: datetime | None = Field(
        None, description="Timestamp of last settings update"
    )
    editable_settings: list[str] = Field(
        default_factory=lambda: sorted(SELF_SERVICE_CRAWLER_SETTING_KEYS),
        description="Setting keys editable through the tenant admin settings endpoint",
    )
    specs: dict[str, CrawlerSettingSpecPublic] = Field(
        default_factory=_self_service_setting_specs,
        description="Validation metadata for tenant-admin editable crawler settings",
    )


class DeleteSettingsResponse(BaseModel):
    tenant_id: UUID = Field(..., description="Tenant UUID")
    message: str = Field(..., description="Confirmation message")
    deleted_keys: list[str] = Field(
        ..., description="List of setting keys that were removed"
    )
