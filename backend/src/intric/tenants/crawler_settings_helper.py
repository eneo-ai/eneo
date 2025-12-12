"""
Helper functions for retrieving tenant-specific crawler settings.

This module provides utilities to get crawler settings with tenant override support.
Settings are retrieved hierarchically: tenant-specific > environment defaults.

IMPORTANT: CRAWLER_SETTING_SPECS is the SINGLE SOURCE OF TRUTH for all crawler settings.
It defines types, validation ranges, defaults, and descriptions.
All consumers (tenant.py validator, router Pydantic model) should import from here.
"""

from typing import Any, TypeVar

from intric.main.config import get_settings

T = TypeVar("T")

# Buffer for TTL vs max_age validation (5 minutes)
# Used by: config.py startup validation, tenant_service.py API validation
# Why: Ensures TTL >= max_age + buffer to prevent slot leaks when flag expires before job timeout
TTL_MAX_AGE_BUFFER_SECONDS: int = 300

# Single source of truth for all crawler settings
# Used by: get_crawler_setting(), get_all_crawler_settings(), tenant.py validator, router
CRAWLER_SETTING_SPECS: dict[str, dict[str, Any]] = {
    "crawl_max_length": {
        "type": int,
        "min": 60,
        "max": 86400,
        "env_attr": "crawl_max_length",
        "description": "Maximum crawl duration in seconds (1 min to 24 hours)",
    },
    "download_timeout": {
        "type": int,
        "min": 10,
        "max": 300,
        "default": 90,
        "description": "Per-request download timeout in seconds (10s to 5 min)",
    },
    "download_max_size": {
        "type": int,
        "min": 1048576,
        "max": 1073741824,
        "env_attr": "download_max_size",
        "description": "Maximum file size for crawler downloads in bytes (1MB to 1GB)",
    },
    "dns_timeout": {
        "type": int,
        "min": 5,
        "max": 120,
        "default": 30,
        "description": "DNS resolution timeout in seconds (5s to 2 min)",
    },
    "retry_times": {
        "type": int,
        "min": 0,
        "max": 10,
        "default": 2,
        "description": "Number of retry attempts per request (0 to 10)",
    },
    "closespider_itemcount": {
        "type": int,
        "min": 100,
        "max": 100000,
        "env_attr": "closespider_itemcount",
        "description": "Maximum pages to crawl before stopping (100 to 100k)",
    },
    "obey_robots": {
        "type": bool,
        "env_attr": "obey_robots",
        "description": "Whether to respect robots.txt rules",
    },
    "autothrottle_enabled": {
        "type": bool,
        "env_attr": "autothrottle_enabled",
        "description": "Enable automatic request throttling based on server response times",
    },
    "tenant_worker_concurrency_limit": {
        "type": int,
        "min": 0,
        "max": 50,
        "env_attr": "tenant_worker_concurrency_limit",
        "description": "Maximum concurrent crawl jobs per tenant (0 = unlimited, 1 to 50)",
    },
    "crawl_stale_threshold_minutes": {
        "type": int,
        "min": 5,
        "max": 1440,
        "env_attr": "crawl_stale_threshold_minutes",
        "description": "Minutes without activity before IN_PROGRESS job is considered stale (5 min to 24 hours)",
    },
    "queued_stale_threshold_minutes": {
        "type": int,
        "min": 1,
        "max": 60,
        "default": 5,
        "description": "Minutes before QUEUED job is considered orphaned and allows new crawl (1 to 60 min)",
    },
    "crawl_heartbeat_interval_seconds": {
        "type": int,
        "min": 30,
        "max": 3600,
        "env_attr": "crawl_heartbeat_interval_seconds",
        "description": "Heartbeat interval to signal job is alive (30s to 1 hour)",
    },
    "crawl_feeder_enabled": {
        "type": bool,
        "env_attr": "crawl_feeder_enabled",
        "description": "Enable crawl feeder service for rate-limited job enqueueing",
    },
    "crawl_feeder_interval_seconds": {
        "type": int,
        "min": 5,
        "max": 300,
        "env_attr": "crawl_feeder_interval_seconds",
        "description": "Feeder check interval in seconds (5s to 5 min)",
    },
    "crawl_feeder_batch_size": {
        "type": int,
        "min": 1,
        "max": 100,
        "env_attr": "crawl_feeder_batch_size",
        "description": "Maximum jobs to enqueue per feeder cycle per tenant (1 to 100)",
    },
    "crawl_job_max_age_seconds": {
        "type": int,
        "min": 300,
        "max": 7200,
        "env_attr": "crawl_job_max_age_seconds",
        "description": "Maximum job retry age before permanent failure (5 min to 2 hours)",
    },
    "tenant_worker_semaphore_ttl_seconds": {
        "type": int,
        "min": 3600,       # 1 hour minimum
        "max": 86400,      # 24 hours maximum
        "env_attr": "tenant_worker_semaphore_ttl_seconds",
        "description": "Concurrency slot TTL in seconds - must be >= crawl_max_length (1h to 24h)",
    },
    "crawl_page_batch_size": {
        "type": int,
        "min": 10,
        "max": 1000,
        "env_attr": "crawl_page_batch_size",
        "description": "Commit after every N pages during crawl (10 to 1000)",
    },
}


def _get_setting_default(setting_name: str, spec: dict[str, Any]) -> Any:
    """Get the default value for a setting from env or hardcoded default."""
    # If spec has hardcoded default, use it
    if "default" in spec:
        return spec["default"]

    # Otherwise, get from environment Settings
    if "env_attr" in spec:
        settings = get_settings()
        return getattr(settings, spec["env_attr"])

    raise KeyError(f"Setting {setting_name} has no default or env_attr defined")


def get_crawler_setting(
    setting_name: str,
    tenant_crawler_settings: dict[str, Any] | None,
    default: T | None = None,
) -> T:
    """
    Get a crawler setting value with tenant override support.

    Lookup order:
    1. Tenant-specific override (from crawler_settings JSONB)
    2. Environment variable default (from Settings)
    3. Hardcoded default (from CRAWLER_SETTING_SPECS)

    Args:
        setting_name: Name of the setting (e.g., "download_timeout", "crawl_max_length")
        tenant_crawler_settings: Tenant's crawler_settings dict (from TenantInDB.crawler_settings)
        default: Optional fallback if setting not found in either source

    Returns:
        The setting value from tenant override or environment default

    Example:
        # In crawl_tasks.py
        tenant = await get_tenant(tenant_id)
        timeout = get_crawler_setting(
            "download_timeout",
            tenant.crawler_settings,
            default=90
        )
    """
    # Check tenant override first
    if tenant_crawler_settings and setting_name in tenant_crawler_settings:
        return tenant_crawler_settings[setting_name]

    # Check if it's a known setting
    if setting_name in CRAWLER_SETTING_SPECS:
        return _get_setting_default(setting_name, CRAWLER_SETTING_SPECS[setting_name])

    # Unknown setting - return explicit default or raise
    if default is not None:
        return default

    raise KeyError(f"Unknown crawler setting: {setting_name}")


def get_all_crawler_settings(
    tenant_crawler_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Get all crawler settings merged with defaults.

    Args:
        tenant_crawler_settings: Tenant's crawler_settings dict

    Returns:
        Complete settings dict with tenant overrides merged with defaults
    """
    # Build defaults from specs
    result = {}
    for setting_name, spec in CRAWLER_SETTING_SPECS.items():
        result[setting_name] = _get_setting_default(setting_name, spec)

    # Merge tenant overrides
    if tenant_crawler_settings:
        result.update(tenant_crawler_settings)

    return result


def validate_crawler_setting(key: str, value: Any) -> list[str]:
    """
    Validate a single crawler setting against specs.

    Args:
        key: Setting name
        value: Value to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    if key not in CRAWLER_SETTING_SPECS:
        errors.append(
            f"Invalid crawler setting: {key}. "
            f"Valid settings: {list(CRAWLER_SETTING_SPECS.keys())}"
        )
        return errors

    spec = CRAWLER_SETTING_SPECS[key]
    expected_type = spec["type"]

    if not isinstance(value, expected_type):
        errors.append(
            f"Setting {key} must be {expected_type.__name__}, "
            f"got {type(value).__name__}"
        )
        return errors

    # Range validation for integers
    if expected_type == int:
        min_val = spec.get("min")
        max_val = spec.get("max")
        if min_val is not None and max_val is not None:
            if value < min_val or value > max_val:
                errors.append(
                    f"Setting {key} must be between {min_val} and {max_val}, "
                    f"got {value}"
                )

    return errors
