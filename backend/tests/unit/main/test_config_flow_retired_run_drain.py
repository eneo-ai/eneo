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
}


def make_settings(**overrides: object) -> Settings:
    return Settings(**{**_BASE_KWARGS, **overrides})


def test_the_drain_runs_every_minute_by_default() -> None:
    assert make_settings().flow_retired_run_drain_interval_seconds == 60


@pytest.mark.parametrize("seconds", [1, 15, 30, 60])
def test_a_divisor_of_sixty_is_accepted(seconds: int) -> None:
    settings = make_settings(flow_retired_run_drain_interval_seconds=seconds)
    assert settings.flow_retired_run_drain_interval_seconds == seconds


@pytest.mark.parametrize("seconds", [0, -5, 7, 90])
def test_other_intervals_stop_startup(seconds: int) -> None:
    with pytest.raises(SystemExit):
        make_settings(flow_retired_run_drain_interval_seconds=seconds)
