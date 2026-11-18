"""The worker readiness probe tells a failed probe apart from stopped workers."""

from __future__ import annotations

from typing import Any

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from eneo.tasks import health
from eneo.tasks.contracts import TaskWorkerReadiness


class _FakeRedis:
    """Answers `mget` with fixed values, or raises what it was given."""

    def __init__(self, answer: list[str | None] | BaseException) -> None:
        self._answer = answer
        self.closed = False

    async def mget(self, *keys: str) -> list[str | None]:
        if isinstance(self._answer, BaseException):
            raise self._answer
        return self._answer

    async def aclose(self) -> None:
        self.closed = True


def _probe(monkeypatch: pytest.MonkeyPatch, answer: Any) -> _FakeRedis:
    fake = _FakeRedis(answer)
    monkeypatch.setattr(health, "Redis", lambda **_: fake)
    return fake


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["ok", "ok"], TaskWorkerReadiness(True, True, probe_ok=True)),
        ([None, "ok"], TaskWorkerReadiness(False, True, probe_ok=True)),
        (["ok", None], TaskWorkerReadiness(True, False, probe_ok=True)),
        ([None, None], TaskWorkerReadiness(False, False, probe_ok=True)),
    ],
    ids=["both-run", "execution-missing", "maintenance-missing", "both-missing"],
)
async def test_a_successful_probe_reports_each_health_key(
    monkeypatch: pytest.MonkeyPatch,
    values: list[str | None],
    expected: TaskWorkerReadiness,
) -> None:
    fake = _probe(monkeypatch, values)

    assert await health.load_task_worker_readiness() == expected
    assert fake.closed


@pytest.mark.parametrize(
    "failure",
    [RedisConnectionError("down"), TimeoutError(), OSError("refused")],
    ids=["redis-error", "timeout", "os-error"],
)
async def test_a_failed_probe_says_so_and_reports_no_worker_as_ready(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    fake = _probe(monkeypatch, failure)

    assert await health.load_task_worker_readiness() == TaskWorkerReadiness(
        execution_ready=False, maintenance_ready=False, probe_ok=False
    )
    assert fake.closed
