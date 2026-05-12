from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.tenants.crawler_settings_helper import (
    SELF_SERVICE_CRAWLER_SETTING_KEYS,
    get_all_crawler_settings,
)


def test_effective_crawler_settings_rejects_http_cache_fields():
    from intric.tenants.crawler_settings_models import (
        CrawlerSettingsResponse,
        EffectiveCrawlerSettings,
    )

    settings = get_all_crawler_settings({})
    settings["crawl_http_cache_enabled"] = True

    with pytest.raises(ValidationError):
        EffectiveCrawlerSettings.model_validate(settings)

    response = CrawlerSettingsResponse(
        tenant_id=uuid4(),
        settings=get_all_crawler_settings({}),
        overrides=[],
        updated_at=None,
    )
    assert "crawl_http_cache_enabled" not in response.model_dump()["settings"]


def test_self_service_crawler_settings_update_rejects_operator_knobs():
    from intric.tenants.crawler_settings_models import CrawlerSettingsSelfServiceUpdate

    for operator_key, value in [
        ("tenant_worker_concurrency_limit", 10),
        ("crawl_page_batch_size", 200),
        ("crawl_max_length", 7200),
    ]:
        with pytest.raises(ValidationError):
            CrawlerSettingsSelfServiceUpdate.model_validate({operator_key: value})


def test_self_service_crawler_settings_update_allows_admin_safe_settings():
    from intric.tenants.crawler_settings_models import CrawlerSettingsSelfServiceUpdate

    update = CrawlerSettingsSelfServiceUpdate.model_validate(
        {
            "crawl_sitemap_lastmod_skip_enabled": True,
            "obey_robots": True,
            "autothrottle_enabled": False,
            "download_max_size": 52_428_800,
            "download_timeout": 120,
            "dns_timeout": 45,
            "retry_times": 3,
            "closespider_itemcount": 5_000,
        }
    )

    assert update.model_dump(exclude_none=True) == {
        "crawl_sitemap_lastmod_skip_enabled": True,
        "obey_robots": True,
        "autothrottle_enabled": False,
        "download_max_size": 52_428_800,
        "download_timeout": 120,
        "dns_timeout": 45,
        "retry_times": 3,
        "closespider_itemcount": 5_000,
    }


def test_self_service_model_fields_match_canonical_allowlist():
    from intric.tenants.crawler_settings_models import CrawlerSettingsSelfServiceUpdate

    assert set(CrawlerSettingsSelfServiceUpdate.model_fields) == set(
        SELF_SERVICE_CRAWLER_SETTING_KEYS
    )


def test_crawler_setting_literals_match_spec_keys():
    from typing import get_args

    from intric.tenants.crawler_settings_helper import (
        CRAWLER_SETTING_SPECS,
        BoolCrawlerSetting,
        IntCrawlerSetting,
    )

    typed_setting_names = set(get_args(IntCrawlerSetting)) | set(
        get_args(BoolCrawlerSetting)
    )

    assert typed_setting_names == set(CRAWLER_SETTING_SPECS)
