"""The readback runs in a process of its own (`run-cron --until-complete
run_retention`), so the command starts what the retention tasks need there,
the process's Redis clients included, and stops it again."""

from unittest.mock import AsyncMock

import pytest

from eneo.main import retention_readback
from eneo.main.exceptions import NotReadyException
from eneo.redis.clients import redis_clients


class _Runtime:
    def start(self, *, encryption: object) -> None:
        pass

    async def validate_configuration(self) -> None:
        pass

    async def stop(self) -> None:
        pass


@pytest.mark.asyncio
async def test_the_readback_process_runs_with_its_own_redis_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached: list[object] = []

    async def read_back(*, emit: object) -> bool:
        reached.append(redis_clients.commands())
        return True

    monkeypatch.setattr(retention_readback, "read_back_retention", read_back)
    monkeypatch.setattr(retention_readback, "object_content_runtime", _Runtime())
    monkeypatch.setattr(retention_readback.sessionmanager, "init", lambda url: None)
    monkeypatch.setattr(retention_readback.sessionmanager, "close", AsyncMock())
    # A new process: nothing has started the clients yet.
    await redis_clients.stop()

    assert await retention_readback._main() == 0

    assert len(reached) == 1
    with pytest.raises(NotReadyException):
        redis_clients.commands()
