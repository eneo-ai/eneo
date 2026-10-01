import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from eneo.main.config import (
    JWT_EXPIRY_TIME_MAXIMUM_MINUTES,
    Settings,
    get_settings,
)


def _with_worker_capacity(settings: Settings, **updates: int | None) -> Settings:
    return settings.model_copy(update=updates)


@pytest.mark.parametrize(
    "field,value",
    [
        ("db_pool_size", 0),
        ("db_pool_max_overflow", -1),
        ("db_pool_timeout", 0),
        ("db_pool_recycle", -2),
    ],
)
def test_invalid_database_pool_policy_is_rejected(field, value):
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate({**get_settings().model_dump(), field: value})


def test_crawl_capacity_defaults_to_the_dedicated_worker_capacity() -> None:
    settings = _with_worker_capacity(
        get_settings(),
        worker_max_jobs=15,
        crawl_job_concurrency_limit=None,
    )

    assert settings.effective_crawl_job_concurrency_limit == 15


def test_single_slot_dedicated_worker_can_execute_one_crawl() -> None:
    settings = _with_worker_capacity(
        get_settings(),
        worker_max_jobs=1,
        crawl_job_concurrency_limit=None,
    )

    assert settings.effective_crawl_job_concurrency_limit == 1


def test_explicit_crawl_capacity_supports_multi_worker_clusters() -> None:
    settings = _with_worker_capacity(
        get_settings(),
        worker_max_jobs=15,
        crawl_job_concurrency_limit=30,
    )

    assert settings.effective_crawl_job_concurrency_limit == 30


def test_tenant_crawl_ceiling_defaults_to_four() -> None:
    values = get_settings().model_dump()
    values.pop("crawl_job_tenant_concurrency_limit", None)
    settings = Settings.model_validate(values)

    assert settings.crawl_job_tenant_concurrency_limit == 4


@pytest.mark.parametrize("limit", [None, 1, 7])
def test_tenant_crawl_ceiling_accepts_unset_or_positive_values(
    limit: int | None,
) -> None:
    settings = Settings.model_validate(
        {**get_settings().model_dump(), "crawl_job_tenant_concurrency_limit": limit}
    )

    assert settings.crawl_job_tenant_concurrency_limit == limit


@pytest.mark.parametrize("limit", [0, -1])
def test_tenant_crawl_ceiling_rejects_nonpositive_values(limit: int) -> None:
    with pytest.raises(ValidationError, match="crawl_job_tenant_concurrency_limit"):
        Settings.model_validate(
            {**get_settings().model_dump(), "crawl_job_tenant_concurrency_limit": limit}
        )


def test_crawler_env_templates_only_publish_runtime_settings() -> None:
    backend_root = Path(__file__).parents[3]
    templates = (
        backend_root / ".env.template",
        backend_root.parent / "docs/deployment/env_backend.template",
    )
    crawler_names = {
        "DOWNLOAD_MAX_SIZE",
        "OBEY_ROBOTS",
        "AUTOTHROTTLE_ENABLED",
        "CLOSESPIDER_ITEMCOUNT",
        "WORKER_MAX_JOBS",
    }
    declared: set[str] = set()
    for template in templates:
        for name in re.findall(r"(?m)^#?\s*([A-Z][A-Z0-9_]+)=", template.read_text()):
            if (
                name.startswith(("CRAWL_", "TENANT_WORKER_", "ORPHAN_CRAWL_"))
                or name in crawler_names
            ):
                declared.add(name)

    runtime_fields = Settings.model_fields
    assert declared
    assert {name for name in declared if name.lower() not in runtime_fields} == set()


@pytest.mark.parametrize("minutes", [1, 60, 1440, JWT_EXPIRY_TIME_MAXIMUM_MINUTES])
def test_jwt_expiry_time_accepts_positive_minutes(minutes: int) -> None:
    settings = Settings.model_validate(
        {**get_settings().model_dump(), "jwt_expiry_time": minutes}
    )

    assert settings.jwt_expiry_time == minutes


@pytest.mark.parametrize("minutes", [0, -1])
def test_jwt_expiry_time_rejects_nonpositive_values(minutes: int) -> None:
    with pytest.raises(ValidationError, match="JWT_EXPIRY_TIME"):
        Settings.model_validate(
            {**get_settings().model_dump(), "jwt_expiry_time": minutes}
        )


@pytest.mark.parametrize("minutes", [JWT_EXPIRY_TIME_MAXIMUM_MINUTES + 1, 86400])
def test_jwt_expiry_time_rejects_values_beyond_thirty_days(minutes: int) -> None:
    # 86400 is the value earlier templates shipped when the unit was mislabelled
    # as seconds; it means 60 days and must be corrected, not reinterpreted.
    with pytest.raises(ValidationError, match="30 days"):
        Settings.model_validate(
            {**get_settings().model_dump(), "jwt_expiry_time": minutes}
        )


@pytest.mark.parametrize("key", ["", "   ", "short-key", "x" * 31])
def test_url_signing_key_rejects_blank_or_short_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="URL_SIGNING_KEY") as exc_info:
        Settings.model_validate({**get_settings().model_dump(), "url_signing_key": key})

    if key.strip():
        assert key not in str(exc_info.value)


def test_url_signing_key_accepts_thirty_two_bytes() -> None:
    settings = Settings.model_validate(
        {**get_settings().model_dump(), "url_signing_key": "k" * 32}
    )

    assert settings.url_signing_key == "k" * 32


def test_settings_validation_errors_never_echo_values() -> None:
    secret = "a-secret-that-must-not-be-printed-anywhere"
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate(
            {
                **get_settings().model_dump(),
                "jwt_secret": secret,
                "url_signing_key": "x",
            }
        )

    assert secret not in str(exc_info.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_redis_credentials_mean_no_authentication(blank: str) -> None:
    settings = Settings.model_validate(
        {
            **get_settings().model_dump(),
            "redis_username": blank,
            "redis_password": blank,
        }
    )

    assert settings.redis_username is None
    assert settings.redis_password is None


def test_redis_username_requires_a_password() -> None:
    with pytest.raises(ValidationError, match="REDIS_USERNAME"):
        Settings.model_validate(
            {
                **get_settings().model_dump(),
                "redis_username": "eneo",
                "redis_password": None,
            }
        )


def test_get_settings_exits_with_a_readable_message(monkeypatch, caplog) -> None:
    from eneo.main import config

    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setenv("JWT_EXPIRY_TIME", "86400")

    with pytest.raises(SystemExit) as exc_info:
        with caplog.at_level("ERROR"):
            config.get_settings()

    assert exc_info.value.code == 1
    message = caplog.text
    assert "Eneo cannot start until its configuration is corrected" in message
    assert "  JWT_EXPIRY_TIME is the session lifetime in minutes" in message
    assert "86400" not in message
    assert "Traceback" not in message
