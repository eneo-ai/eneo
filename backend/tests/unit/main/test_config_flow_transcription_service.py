from __future__ import annotations

import pytest

from eneo.main.config import Settings

_BASE_KWARGS: dict[str, object] = {
    "postgres_user": "unit_test_user",
    "postgres_host": "localhost",
    "postgres_password": "unit_test_password",
    "postgres_port": 5432,
    "postgres_db": "unit_test_db",
    "redis_host": "localhost",
    "redis_port": 6379,
    "encryption_key": "yPIAaWTENh5knUuz75NYHblR3672X-7lH-W6AD4F1hs=",
    "crawl_max_length": 1800,
    "tenant_worker_semaphore_ttl_seconds": 3600,
}


def make_settings(**overrides: object) -> Settings:
    return Settings(**{**_BASE_KWARGS, **overrides})


def test_unset_service_is_valid_default() -> None:
    settings = make_settings()
    assert settings.flow_transcription_service_url is None


def test_configured_service_requires_api_key() -> None:
    with pytest.raises(SystemExit):
        make_settings(flow_transcription_service_url="http://tolka.test")


def test_configured_service_with_key_is_valid() -> None:
    settings = make_settings(
        flow_transcription_service_url="http://tolka.test",
        flow_transcription_service_api_key="devtoken",
    )
    assert settings.flow_transcription_service_poll_interval_seconds > 0


def test_poll_timeout_must_stay_below_task_execution_timeout() -> None:
    with pytest.raises(SystemExit):
        make_settings(
            flow_transcription_service_url="http://tolka.test",
            flow_transcription_service_api_key="devtoken",
            flow_transcription_service_poll_timeout_seconds=3600,
        )


@pytest.mark.parametrize(
    "field",
    [
        "flow_transcription_service_submit_timeout_seconds",
        "flow_transcription_service_poll_interval_seconds",
        "flow_transcription_service_poll_timeout_seconds",
        "flow_transcription_service_result_timeout_seconds",
    ],
)
def test_timeouts_must_be_positive(field: str) -> None:
    with pytest.raises(SystemExit):
        make_settings(**{field: 0})
