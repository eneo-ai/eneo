"""Unit tests for crawler_settings_helper.py

Tests the single source of truth (CRAWLER_SETTING_SPECS) and helper functions
for tenant-specific crawler settings with hierarchical override support.
"""

import pytest
from unittest.mock import patch, MagicMock

from intric.tenants.crawler_settings_helper import (
    CRAWLER_SETTING_SPECS,
    get_crawler_setting,
    get_all_crawler_settings,
    validate_crawler_setting,
)


class TestCrawlerSettingSpecs:
    """Tests for CRAWLER_SETTING_SPECS structure."""

    def test_all_settings_have_required_fields(self):
        """Every setting spec has type field at minimum."""
        for name, spec in CRAWLER_SETTING_SPECS.items():
            assert "type" in spec, f"{name} missing 'type' field"
            assert "description" in spec, f"{name} missing 'description' field"

    def test_integer_settings_have_ranges(self):
        """Integer settings should have min/max constraints."""
        for name, spec in CRAWLER_SETTING_SPECS.items():
            if spec["type"] == int:
                assert "min" in spec, f"{name} missing 'min' field"
                assert "max" in spec, f"{name} missing 'max' field"
                assert spec["min"] <= spec["max"], f"{name} min > max"

    def test_all_settings_have_default_source(self):
        """Every setting must have either 'default' or 'env_attr'."""
        for name, spec in CRAWLER_SETTING_SPECS.items():
            has_default = "default" in spec
            has_env_attr = "env_attr" in spec
            assert has_default or has_env_attr, (
                f"{name} needs 'default' or 'env_attr'"
            )

    def test_expected_settings_count(self):
        """Verify we have all 15 crawler settings."""
        assert len(CRAWLER_SETTING_SPECS) == 15

    def test_known_settings_present(self):
        """Verify all known settings are present."""
        expected = [
            "crawl_max_length",
            "download_timeout",
            "download_max_size",
            "dns_timeout",
            "retry_times",
            "closespider_itemcount",
            "obey_robots",
            "autothrottle_enabled",
            "tenant_worker_concurrency_limit",
            "crawl_stale_threshold_minutes",
            "crawl_heartbeat_interval_seconds",
            "crawl_feeder_enabled",
            "crawl_feeder_interval_seconds",
            "crawl_feeder_batch_size",
            "crawl_job_max_age_seconds",
        ]
        for name in expected:
            assert name in CRAWLER_SETTING_SPECS, f"Missing setting: {name}"


class TestGetCrawlerSetting:
    """Tests for get_crawler_setting() function."""

    def test_returns_tenant_override_when_present(self):
        """Tenant-specific value takes precedence over env defaults."""
        tenant_settings = {"download_timeout": 120}
        result = get_crawler_setting("download_timeout", tenant_settings)
        assert result == 120

    def test_returns_hardcoded_default_when_no_tenant_override(self):
        """Falls back to hardcoded default for settings without env_attr."""
        tenant_settings = {}
        result = get_crawler_setting("download_timeout", tenant_settings)
        # download_timeout has hardcoded default of 90
        assert result == 90

    def test_returns_explicit_default_for_unknown_setting(self):
        """Returns provided default for unknown settings."""
        result = get_crawler_setting("nonexistent_setting", {}, default=999)
        assert result == 999

    def test_raises_keyerror_for_unknown_without_default(self):
        """Raises KeyError for unknown setting with no default."""
        with pytest.raises(KeyError, match="Unknown crawler setting"):
            get_crawler_setting("nonexistent_setting", {})

    def test_handles_none_tenant_settings(self):
        """Works correctly when tenant_crawler_settings is None."""
        result = get_crawler_setting("download_timeout", None)
        assert result == 90  # Hardcoded default

    def test_all_known_settings_have_defaults(self):
        """Every known setting returns a value without explicit default."""
        with patch("intric.tenants.crawler_settings_helper.get_settings") as mock:
            # Mock settings with all env attrs
            mock_settings = MagicMock()
            mock_settings.crawl_max_length = 14400
            mock_settings.closespider_itemcount = 20000
            mock_settings.download_max_size = 10485760
            mock_settings.obey_robots = True
            mock_settings.autothrottle_enabled = True
            mock_settings.tenant_worker_concurrency_limit = 4
            mock_settings.crawl_stale_threshold_minutes = 30
            mock_settings.crawl_heartbeat_interval_seconds = 300
            mock_settings.crawl_feeder_enabled = False
            mock_settings.crawl_feeder_interval_seconds = 10
            mock_settings.crawl_feeder_batch_size = 10
            mock_settings.crawl_job_max_age_seconds = 1800
            mock.return_value = mock_settings

            for setting in CRAWLER_SETTING_SPECS.keys():
                result = get_crawler_setting(setting, {})
                assert result is not None, f"{setting} should have a default"

    def test_tenant_override_takes_precedence_over_env(self):
        """Tenant override beats environment default."""
        with patch("intric.tenants.crawler_settings_helper.get_settings") as mock:
            mock_settings = MagicMock()
            mock_settings.crawl_max_length = 14400  # Env default
            mock.return_value = mock_settings

            tenant_settings = {"crawl_max_length": 7200}  # Tenant override
            result = get_crawler_setting("crawl_max_length", tenant_settings)
            assert result == 7200


class TestGetAllCrawlerSettings:
    """Tests for get_all_crawler_settings() function."""

    def test_returns_all_settings_with_defaults(self):
        """Returns complete settings dict with env defaults."""
        with patch("intric.tenants.crawler_settings_helper.get_settings") as mock:
            mock_settings = MagicMock()
            mock_settings.crawl_max_length = 14400
            mock_settings.closespider_itemcount = 20000
            mock_settings.download_max_size = 10485760
            mock_settings.obey_robots = True
            mock_settings.autothrottle_enabled = True
            mock_settings.tenant_worker_concurrency_limit = 4
            mock_settings.crawl_stale_threshold_minutes = 30
            mock_settings.crawl_heartbeat_interval_seconds = 300
            mock_settings.crawl_feeder_enabled = False
            mock_settings.crawl_feeder_interval_seconds = 10
            mock_settings.crawl_feeder_batch_size = 10
            mock_settings.crawl_job_max_age_seconds = 1800
            mock.return_value = mock_settings

            result = get_all_crawler_settings({})
            assert "download_timeout" in result
            assert "crawl_max_length" in result
            assert len(result) == 15

    def test_tenant_overrides_merged_correctly(self):
        """Tenant-specific values override defaults."""
        with patch("intric.tenants.crawler_settings_helper.get_settings") as mock:
            mock_settings = MagicMock()
            mock_settings.crawl_max_length = 14400
            mock_settings.closespider_itemcount = 20000
            mock_settings.download_max_size = 10485760
            mock_settings.obey_robots = True
            mock_settings.autothrottle_enabled = True
            mock_settings.tenant_worker_concurrency_limit = 4
            mock_settings.crawl_stale_threshold_minutes = 30
            mock_settings.crawl_heartbeat_interval_seconds = 300
            mock_settings.crawl_feeder_enabled = False
            mock_settings.crawl_feeder_interval_seconds = 10
            mock_settings.crawl_feeder_batch_size = 10
            mock_settings.crawl_job_max_age_seconds = 1800
            mock.return_value = mock_settings

            tenant_settings = {"download_timeout": 200, "dns_timeout": 60}
            result = get_all_crawler_settings(tenant_settings)
            assert result["download_timeout"] == 200
            assert result["dns_timeout"] == 60
            # Non-overridden should have defaults
            assert result["retry_times"] == 2

    def test_handles_none_input(self):
        """Works correctly with None input."""
        with patch("intric.tenants.crawler_settings_helper.get_settings") as mock:
            mock_settings = MagicMock()
            mock_settings.crawl_max_length = 14400
            mock_settings.closespider_itemcount = 20000
            mock_settings.download_max_size = 10485760
            mock_settings.obey_robots = True
            mock_settings.autothrottle_enabled = True
            mock_settings.tenant_worker_concurrency_limit = 4
            mock_settings.crawl_stale_threshold_minutes = 30
            mock_settings.crawl_heartbeat_interval_seconds = 300
            mock_settings.crawl_feeder_enabled = False
            mock_settings.crawl_feeder_interval_seconds = 10
            mock_settings.crawl_feeder_batch_size = 10
            mock_settings.crawl_job_max_age_seconds = 1800
            mock.return_value = mock_settings

            result = get_all_crawler_settings(None)
            assert len(result) == 15


class TestValidateCrawlerSetting:
    """Tests for validate_crawler_setting() function."""

    def test_valid_integer_setting(self):
        """Valid integer in range returns no errors."""
        errors = validate_crawler_setting("download_timeout", 90)
        assert errors == []

    def test_invalid_setting_name(self):
        """Unknown setting name returns error."""
        errors = validate_crawler_setting("nonexistent", 100)
        assert len(errors) == 1
        assert "Invalid crawler setting" in errors[0]

    def test_wrong_type_returns_error(self):
        """Wrong type returns type error."""
        errors = validate_crawler_setting("download_timeout", "not_an_int")
        assert len(errors) == 1
        assert "must be int" in errors[0]

    def test_below_min_returns_error(self):
        """Value below minimum returns range error."""
        # download_timeout min is 10
        errors = validate_crawler_setting("download_timeout", 5)
        assert len(errors) == 1
        assert "must be between" in errors[0]

    def test_above_max_returns_error(self):
        """Value above maximum returns range error."""
        # download_timeout max is 300
        errors = validate_crawler_setting("download_timeout", 500)
        assert len(errors) == 1
        assert "must be between" in errors[0]

    def test_valid_boolean_setting(self):
        """Valid boolean returns no errors."""
        errors = validate_crawler_setting("obey_robots", True)
        assert errors == []
        errors = validate_crawler_setting("obey_robots", False)
        assert errors == []

    def test_boolean_wrong_type(self):
        """Non-boolean for boolean setting returns error."""
        errors = validate_crawler_setting("obey_robots", "true")
        assert len(errors) == 1
        assert "must be bool" in errors[0]

    def test_boundary_values_valid(self):
        """Boundary values at min/max are valid."""
        # download_timeout: min=10, max=300
        errors = validate_crawler_setting("download_timeout", 10)
        assert errors == []
        errors = validate_crawler_setting("download_timeout", 300)
        assert errors == []
