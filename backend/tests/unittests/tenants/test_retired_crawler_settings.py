from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.tenants.crawler_settings_helper import (
    RETIRED_CRAWLER_SETTINGS,
    get_all_crawler_settings,
    get_crawler_setting,
)
from eneo.tenants.presentation.tenant_crawler_settings_router import (
    CrawlerSettingsUpdate,
)
from eneo.tenants.tenant import TenantInDB, TenantWithMaskedCredentials


def test_legacy_retired_settings_are_preserved_during_tenant_hydration() -> None:
    stored_settings = {
        "crawl_feeder_enabled": True,
        "tenant_worker_concurrency_limit": 4,
        "download_timeout": 120,
    }

    tenant = TenantInDB(
        id=uuid4(),
        name="tenant",
        display_name="Tenant",
        quota_limit=1,
        crawler_settings=stored_settings,
    )

    assert tenant.crawler_settings == stored_settings


def test_retired_settings_are_absent_from_effective_settings() -> None:
    effective = get_all_crawler_settings(
        {
            "crawl_feeder_enabled": True,
            "crawl_job_max_age_seconds": 1800,
            "download_timeout": 120,
        }
    )

    assert effective["download_timeout"] == 120
    assert RETIRED_CRAWLER_SETTINGS.isdisjoint(effective)


def test_retired_settings_are_absent_from_public_tenant_projection() -> None:
    tenant = TenantInDB(
        id=uuid4(),
        name="tenant",
        display_name="Tenant",
        quota_limit=1,
        crawler_settings={
            "crawl_feeder_enabled": True,
            "download_timeout": 120,
        },
    )

    public_tenant = TenantWithMaskedCredentials.from_tenant(tenant)

    assert public_tenant.crawler_settings == {"download_timeout": 120}


def test_tenant_serialization_filters_retired_settings_at_model_boundary() -> None:
    tenant = TenantInDB(
        id=uuid4(),
        name="tenant",
        display_name="Tenant",
        quota_limit=1,
        crawler_settings={
            "crawl_feeder_enabled": True,
            "download_timeout": 120,
        },
    )

    assert tenant.crawler_settings["crawl_feeder_enabled"] is True
    assert tenant.model_dump()["crawler_settings"] == {"download_timeout": 120}


def test_runtime_accessor_rejects_retired_persisted_setting() -> None:
    with pytest.raises(KeyError, match="Unknown crawler setting"):
        get_crawler_setting(
            "crawl_feeder_enabled",
            {"crawl_feeder_enabled": True},
        )


def test_retired_settings_cannot_be_written_through_the_public_api() -> None:
    assert RETIRED_CRAWLER_SETTINGS.isdisjoint(CrawlerSettingsUpdate.model_fields)

    with pytest.raises(ValidationError):
        CrawlerSettingsUpdate.model_validate({"crawl_feeder_enabled": True})


def test_unknown_settings_cannot_be_silently_ignored_by_the_public_api() -> None:
    with pytest.raises(ValidationError):
        CrawlerSettingsUpdate.model_validate({"crawl_heartbeet_seconds": 30})
