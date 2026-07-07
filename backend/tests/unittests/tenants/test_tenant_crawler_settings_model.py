"""TenantInDB.crawler_settings validation.

Guards the read path: a tenant row must still load after a crawler setting is
retired from CRAWLER_SETTING_SPECS. Retired keys are dropped on load; genuinely
unknown keys still fail validation.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.tenants.crawler_settings_helper import RETIRED_CRAWLER_SETTING_KEYS
from eneo.tenants.tenant import TenantInDB


def _tenant(crawler_settings: dict) -> TenantInDB:
    return TenantInDB(
        id=uuid4(),
        name="test",
        quota_limit=1024**3,
        crawler_settings=crawler_settings,
    )


def test_retired_keys_are_dropped_on_load():
    stored = {key: 1 for key in RETIRED_CRAWLER_SETTING_KEYS}
    tenant = _tenant(stored)
    assert tenant.crawler_settings == {}


def test_retired_keys_dropped_but_valid_keys_kept():
    tenant = _tenant({"download_timeout": 90, "obey_robots": True})
    assert tenant.crawler_settings == {"download_timeout": 90}


def test_unknown_key_still_rejected():
    with pytest.raises(ValidationError):
        _tenant({"totally_unknown_setting": 1})


def test_out_of_range_valid_key_still_rejected():
    with pytest.raises(ValidationError):
        _tenant({"download_timeout": 5})
