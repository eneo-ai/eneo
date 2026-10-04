from __future__ import annotations

import pytest

from tests.unit.main.test_config_flow_transcription_service import make_settings


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
