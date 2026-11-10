"""The readback bounds its rounds: work that keeps being removed fails it,
naming why, instead of keeping traffic closed."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.main import retention_readback
from tests.unittests.data_retention.test_retention_readback import HISTORY, run

_STARTED = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_readback_still_removing_after_its_rounds_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times: list[datetime] = []

    async def started() -> datetime:
        return _STARTED

    async def removing_round(now: datetime) -> list[RetentionRunReport]:
        times.append(now)
        return [run(HISTORY, disposed=1)]

    monkeypatch.setattr(
        retention_readback,
        "retention_task_registrations",
        lambda _settings: [SimpleNamespace(name=HISTORY)],
    )
    monkeypatch.setattr(retention_readback, "database_now", started, raising=False)
    monkeypatch.setattr(
        retention_readback, "run_retention_at", removing_round, raising=False
    )
    monkeypatch.setattr(retention_readback, "_ROUNDS", 3, raising=False)
    lines: list[str] = []

    assert await retention_readback.read_back_retention(emit=lines.append) is False

    assert lines[-2:] == ["retention: not complete", "  still removing after 3 rounds"]
    assert times == [_STARTED] * 3
