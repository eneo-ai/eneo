"""
Helper functions for retrieving tenant-specific crawler settings.

This module provides utilities to get crawler settings with tenant override support.
Settings are retrieved hierarchically: tenant-specific > environment defaults.

IMPORTANT: CRAWLER_SETTING_SPECS is the SINGLE SOURCE OF TRUTH for all crawler settings.
It defines types, validation ranges, defaults, and descriptions.
All consumers (tenant.py validator, router Pydantic model) should import from here.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, TypeVar, get_args, overload
from uuid import UUID

from intric.main.config import get_settings

T = TypeVar("T")
CrawlerSettingValue = int | bool
CrawlerSettingValueType = type[int] | type[bool]

# Setting names grouped by their declared spec type. Keep in sync with
# CRAWLER_SETTING_SPECS below.
IntCrawlerSetting = Literal[
    "crawl_max_length",
    "download_timeout",
    "download_max_size",
    "dns_timeout",
    "retry_times",
    "closespider_itemcount",
    "tenant_worker_concurrency_limit",
    "crawl_stale_threshold_minutes",
    "queued_stale_threshold_minutes",
    "crawl_heartbeat_interval_seconds",
    "crawl_feeder_interval_seconds",
    "crawl_feeder_batch_size",
    "crawl_job_max_age_seconds",
    "tenant_worker_semaphore_ttl_seconds",
    "crawl_page_batch_size",
]

BoolCrawlerSetting = Literal[
    "obey_robots",
    "autothrottle_enabled",
    "crawl_feeder_enabled",
    "crawl_sitemap_lastmod_skip_enabled",
]

CrawlerSetting = IntCrawlerSetting | BoolCrawlerSetting

# Buffer time (5 minutes) between semaphore TTL and job max age
# This ensures the flag doesn't expire before watchdog can kill stale jobs
TTL_MAX_AGE_BUFFER_SECONDS = 300


@dataclass(frozen=True, slots=True)
class CrawlerSettingSpec:
    value_type: CrawlerSettingValueType
    description: str
    min: int | None = None
    max: int | None = None
    default: CrawlerSettingValue | None = None
    env_attr: str | None = None


# Single source of truth for all crawler settings
# Used by: get_crawler_setting(), get_all_crawler_settings(), tenant.py validator, router
CRAWLER_SETTING_SPECS: dict[str, CrawlerSettingSpec] = {
    "crawl_max_length": CrawlerSettingSpec(
        value_type=int,
        min=60,
        max=86400,
        env_attr="crawl_max_length",
        description="Maximum crawl duration in seconds (1 min to 24 hours)",
    ),
    "download_timeout": CrawlerSettingSpec(
        value_type=int,
        min=10,
        max=300,
        default=90,
        description="Per-request download timeout in seconds (10s to 5 min)",
    ),
    "download_max_size": CrawlerSettingSpec(
        value_type=int,
        min=1048576,
        max=1073741824,
        env_attr="download_max_size",
        description="Maximum file size for crawler downloads in bytes (1MB to 1GB)",
    ),
    "dns_timeout": CrawlerSettingSpec(
        value_type=int,
        min=5,
        max=120,
        default=30,
        description="DNS resolution timeout in seconds (5s to 2 min)",
    ),
    "retry_times": CrawlerSettingSpec(
        value_type=int,
        min=0,
        max=10,
        default=2,
        description="Number of retry attempts per request (0 to 10)",
    ),
    "closespider_itemcount": CrawlerSettingSpec(
        value_type=int,
        min=100,
        max=100000,
        env_attr="closespider_itemcount",
        description="Maximum pages to crawl before stopping (100 to 100k)",
    ),
    "obey_robots": CrawlerSettingSpec(
        value_type=bool,
        env_attr="obey_robots",
        description="Whether to respect robots.txt rules",
    ),
    "autothrottle_enabled": CrawlerSettingSpec(
        value_type=bool,
        env_attr="autothrottle_enabled",
        description="Enable automatic request throttling based on server response times",
    ),
    "tenant_worker_concurrency_limit": CrawlerSettingSpec(
        value_type=int,
        min=0,
        max=50,
        env_attr="tenant_worker_concurrency_limit",
        description="Maximum concurrent crawl jobs per tenant (0 = unlimited, 1 to 50)",
    ),
    "crawl_stale_threshold_minutes": CrawlerSettingSpec(
        value_type=int,
        min=5,
        max=1440,
        env_attr="crawl_stale_threshold_minutes",
        description="Minutes without activity before IN_PROGRESS job is considered stale (5 min to 24 hours)",
    ),
    "queued_stale_threshold_minutes": CrawlerSettingSpec(
        value_type=int,
        min=1,
        max=60,
        default=5,
        description="Minutes before QUEUED job is considered orphaned and allows new crawl (1 to 60 min)",
    ),
    "crawl_heartbeat_interval_seconds": CrawlerSettingSpec(
        value_type=int,
        min=30,
        max=3600,
        env_attr="crawl_heartbeat_interval_seconds",
        description="Heartbeat interval to signal job is alive (30s to 1 hour)",
    ),
    "crawl_feeder_enabled": CrawlerSettingSpec(
        value_type=bool,
        env_attr="crawl_feeder_enabled",
        description="Enable crawl feeder service for rate-limited job enqueueing",
    ),
    "crawl_feeder_interval_seconds": CrawlerSettingSpec(
        value_type=int,
        min=5,
        max=300,
        env_attr="crawl_feeder_interval_seconds",
        description="Feeder check interval in seconds (5s to 5 min)",
    ),
    "crawl_feeder_batch_size": CrawlerSettingSpec(
        value_type=int,
        min=1,
        max=100,
        env_attr="crawl_feeder_batch_size",
        description="Maximum jobs to enqueue per feeder cycle per tenant (1 to 100)",
    ),
    "crawl_job_max_age_seconds": CrawlerSettingSpec(
        value_type=int,
        min=300,
        max=7200,
        env_attr="crawl_job_max_age_seconds",
        description="Maximum job retry age before permanent failure (5 min to 2 hours)",
    ),
    "tenant_worker_semaphore_ttl_seconds": CrawlerSettingSpec(
        value_type=int,
        min=3600,
        max=86400,
        env_attr="tenant_worker_semaphore_ttl_seconds",
        description="Concurrency slot TTL in seconds - must be >= crawl_max_length (1h to 24h)",
    ),
    "crawl_page_batch_size": CrawlerSettingSpec(
        value_type=int,
        min=10,
        max=1000,
        env_attr="crawl_page_batch_size",
        description="Commit after every N pages during crawl (10 to 1000)",
    ),
    "crawl_sitemap_lastmod_skip_enabled": CrawlerSettingSpec(
        value_type=bool,
        env_attr="crawl_sitemap_lastmod_skip_enabled",
        description="Enable trusted sitemap lastmod values to retain unchanged URL pages without downloading them",
    ),
}


def _typed_setting_names() -> set[str]:
    return set(get_args(IntCrawlerSetting)) | set(get_args(BoolCrawlerSetting))


if _typed_setting_names() != set(CRAWLER_SETTING_SPECS):
    raise RuntimeError("Crawler setting Literal names must match CRAWLER_SETTING_SPECS")


SELF_SERVICE_CRAWLER_SETTING_KEYS: frozenset[CrawlerSetting] = frozenset(
    {
        "crawl_sitemap_lastmod_skip_enabled",
        "obey_robots",
        "autothrottle_enabled",
        "download_max_size",
        "download_timeout",
        "dns_timeout",
        "retry_times",
        "closespider_itemcount",
        # Tenant-scoped runtime knobs added in the admin-settings expansion
        # sub-tranche 3a — each setting is tenant-scope, bounded by the
        # min/max in its CrawlerSettingSpec, and the value is read at crawl
        # start so a change does not affect already-running crawls.
        # Excluded from this expansion: tenant_worker_concurrency_limit and
        # tenant_worker_semaphore_ttl_seconds (capacity governance —
        # sysadmin), crawl_feeder_* (global feeder runtime), and
        # crawl_page_batch_size (deferred to the token-efficiency tranche
        # because the right operator-facing surface is a retention/cost
        # observation rather than a free knob).
        "crawl_max_length",
        "crawl_stale_threshold_minutes",
        "queued_stale_threshold_minutes",
        "crawl_heartbeat_interval_seconds",
        "crawl_job_max_age_seconds",
    }
)


def get_crawler_setting_specs(
    setting_names: Iterable[str] | None = None,
) -> dict[str, dict[str, object]]:
    names = setting_names if setting_names is not None else CRAWLER_SETTING_SPECS.keys()
    specs: dict[str, dict[str, object]] = {}

    for setting_name in names:
        spec = CRAWLER_SETTING_SPECS[setting_name]
        public_spec: dict[str, object] = {
            "type": "bool" if spec.value_type is bool else "int",
            "description": spec.description,
        }
        if spec.min is not None:
            public_spec["min"] = spec.min
        if spec.max is not None:
            public_spec["max"] = spec.max
        specs[setting_name] = public_spec

    return specs


@dataclass(frozen=True, slots=True)
class InvalidCrawlerSettingOverride:
    name: str
    value: object
    reason: str


@dataclass(frozen=True, slots=True)
class TenantCrawlerSettings:
    values: Mapping[str, CrawlerSettingValue]
    invalid_overrides: tuple[InvalidCrawlerSettingOverride, ...] = ()

    def get(self, setting_name: str) -> CrawlerSettingValue | None:
        return self.values.get(setting_name)

    def as_dict(self) -> dict[str, CrawlerSettingValue]:
        return dict(self.values)

    def warn_invalid_overrides(
        self,
        logger: logging.Logger,
        *,
        tenant_id: UUID | str,
        website_id: UUID | str | None = None,
    ) -> None:
        if not self.invalid_overrides:
            return

        extra: dict[str, object] = {
            "tenant_id": str(tenant_id),
            "invalid_setting_names": [
                override.name for override in self.invalid_overrides
            ],
            "invalid_setting_count": len(self.invalid_overrides),
            "metric_name": "crawler.settings.invalid_overrides_ignored",
            "metric_value": len(self.invalid_overrides),
        }
        if website_id is not None:
            extra["website_id"] = str(website_id)

        logger.warning(
            "Invalid tenant crawler settings ignored; defaults used",
            extra=extra,
        )

    @classmethod
    def from_overrides(
        cls,
        overrides: Mapping[str, object] | None,
    ) -> "TenantCrawlerSettings":
        values = _default_crawler_setting_values()
        invalid_overrides: list[InvalidCrawlerSettingOverride] = []

        if overrides:
            for setting_name, value in overrides.items():
                errors = validate_crawler_setting(setting_name, value)
                if errors:
                    invalid_overrides.append(
                        InvalidCrawlerSettingOverride(
                            name=setting_name,
                            value=value,
                            reason="; ".join(errors),
                        )
                    )
                    continue

                if setting_name in CRAWLER_SETTING_SPECS and isinstance(
                    value, (int, bool)
                ):
                    values[setting_name] = value

        return cls(
            values=MappingProxyType(values),
            invalid_overrides=tuple(invalid_overrides),
        )


def _get_setting_default(
    setting_name: str,
    spec: CrawlerSettingSpec,
) -> CrawlerSettingValue:
    if spec.default is not None:
        return spec.default

    if spec.env_attr is not None:
        settings = get_settings()
        value = _coerce_setting_value(
            expected_type=spec.value_type,
            value=getattr(settings, spec.env_attr),
        )
        if value is not None:
            return value
        raise TypeError(f"Default for {setting_name} must be int or bool")

    raise KeyError(f"Setting {setting_name} has no default or env_attr defined")


def _is_valid_setting_type(
    *,
    expected_type: CrawlerSettingValueType,
    value: object,
) -> bool:
    return _coerce_setting_value(expected_type=expected_type, value=value) is not None


def _coerce_setting_value(
    *,
    expected_type: CrawlerSettingValueType,
    value: object,
) -> CrawlerSettingValue | None:
    if expected_type is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
    if expected_type is bool:
        if isinstance(value, bool):
            return value
        return None
    return None


def _default_crawler_setting_values() -> dict[str, CrawlerSettingValue]:
    values: dict[str, CrawlerSettingValue] = {}
    for setting_name, spec in CRAWLER_SETTING_SPECS.items():
        default_value = _get_setting_default(setting_name, spec)
        if not _is_valid_setting_type(
            expected_type=spec.value_type,
            value=default_value,
        ):
            raise TypeError(f"Default for {setting_name} must be int or bool")
        values[setting_name] = default_value

    return values


@overload
def get_crawler_setting(
    setting_name: IntCrawlerSetting,
    tenant_crawler_settings: TenantCrawlerSettings | Mapping[str, object] | None,
) -> int: ...


@overload
def get_crawler_setting(
    setting_name: BoolCrawlerSetting,
    tenant_crawler_settings: TenantCrawlerSettings | Mapping[str, object] | None,
) -> bool: ...


@overload
def get_crawler_setting(
    setting_name: str,
    tenant_crawler_settings: TenantCrawlerSettings | Mapping[str, object] | None,
    default: T,
) -> T: ...


def get_crawler_setting(
    setting_name: str,
    tenant_crawler_settings: TenantCrawlerSettings | Mapping[str, object] | None,
    default: T | None = None,
) -> T | int | bool:
    """
    Get a crawler setting value with tenant override support.

    Lookup order:
    1. Tenant-specific override (from crawler_settings JSONB)
    2. Environment variable default (from Settings)
    3. Hardcoded default (from CRAWLER_SETTING_SPECS)

    Args:
        setting_name: Name of the setting (e.g., "download_timeout", "crawl_max_length")
        tenant_crawler_settings: Tenant settings snapshot or raw stored overrides
        default: Optional fallback if setting not found in either source

    Returns:
        The setting value from tenant override or environment default

    Example:
        # In crawl_tasks.py
        tenant = await get_tenant(tenant_id)
        timeout = get_crawler_setting(
            "download_timeout",
            tenant_crawler_settings,
            default=90
        )
    """
    if isinstance(tenant_crawler_settings, TenantCrawlerSettings):
        value = tenant_crawler_settings.get(setting_name)
        if value is not None:
            return value

    # Compatibility path for older non-runtime callers; crawler execution should pass
    # a TenantCrawlerSettings snapshot so invalid stored overrides fall back once.
    if (
        tenant_crawler_settings is not None
        and not isinstance(tenant_crawler_settings, TenantCrawlerSettings)
        and setting_name in tenant_crawler_settings
    ):
        value = tenant_crawler_settings[setting_name]
        if setting_name in CRAWLER_SETTING_SPECS:
            errors = validate_crawler_setting(setting_name, value)
            if errors:
                raise ValueError("; ".join(errors))
            if not isinstance(value, (int, bool)):
                raise TypeError(f"Setting {setting_name} must be int or bool")
            return value

    # Check if it's a known setting
    if setting_name in CRAWLER_SETTING_SPECS:
        return _get_setting_default(setting_name, CRAWLER_SETTING_SPECS[setting_name])

    # Unknown setting - return explicit default or raise
    if default is not None:
        return default

    raise KeyError(f"Unknown crawler setting: {setting_name}")


def get_all_crawler_settings(
    tenant_crawler_settings: TenantCrawlerSettings | Mapping[str, object] | None,
) -> dict[str, CrawlerSettingValue]:
    """
    Get all crawler settings merged with defaults.

    Args:
        tenant_crawler_settings: Tenant settings snapshot or raw stored overrides

    Returns:
        Complete settings dict with tenant overrides merged with defaults
    """
    # Build defaults from specs
    if isinstance(tenant_crawler_settings, TenantCrawlerSettings):
        return tenant_crawler_settings.as_dict()

    return TenantCrawlerSettings.from_overrides(tenant_crawler_settings).as_dict()


def validate_crawler_setting(key: str, value: object) -> list[str]:
    """
    Validate a single crawler setting against specs.

    Args:
        key: Setting name
        value: Value to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors: list[str] = []

    if key not in CRAWLER_SETTING_SPECS:
        errors.append(
            f"Invalid crawler setting: {key}. "
            f"Valid settings: {list(CRAWLER_SETTING_SPECS.keys())}"
        )
        return errors

    spec = CRAWLER_SETTING_SPECS[key]
    expected_type = spec.value_type

    if not _is_valid_setting_type(expected_type=expected_type, value=value):
        errors.append(
            f"Setting {key} must be {expected_type.__name__}, "
            f"got {type(value).__name__}"
        )
        return errors

    if expected_type is int and isinstance(value, int) and not isinstance(value, bool):
        int_value = value
        min_val = spec.min
        max_val = spec.max
        if min_val is not None and max_val is not None:
            if int_value < min_val or int_value > max_val:
                errors.append(
                    f"Setting {key} must be between {min_val} and {max_val}, "
                    f"got {int_value}"
                )

    return errors
