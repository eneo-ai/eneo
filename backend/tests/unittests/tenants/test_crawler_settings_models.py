from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.tenants.crawler_settings_helper import get_all_crawler_settings


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

    with pytest.raises(ValidationError):
        CrawlerSettingsSelfServiceUpdate.model_validate(
            {
                "crawl_sitemap_lastmod_skip_enabled": True,
                "download_timeout": 120,
            }
        )


def test_self_service_crawler_settings_update_allows_only_user_safe_settings():
    from intric.tenants.crawler_settings_models import CrawlerSettingsSelfServiceUpdate

    update = CrawlerSettingsSelfServiceUpdate.model_validate(
        {
            "crawl_sitemap_lastmod_skip_enabled": True,
            "obey_robots": True,
            "autothrottle_enabled": False,
        }
    )

    assert update.model_dump(exclude_none=True) == {
        "crawl_sitemap_lastmod_skip_enabled": True,
        "obey_robots": True,
        "autothrottle_enabled": False,
    }


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
