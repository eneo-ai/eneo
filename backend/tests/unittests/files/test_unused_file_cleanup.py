from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from eneo.files import unused_file_cleanup
from eneo.files.unused_file_cleanup import delete_roots_statement
from eneo.files.unused_file_retention_task import UNUSED_FILES_TASK
from eneo.main.exceptions import NotReadyException
from eneo.redis.clients import redis_clients


def test_root_delete_binds_any_batch_size_as_one_array() -> None:
    root_ids = [UUID(int=value) for value in range(1, 40_001)]

    compiled = delete_roots_statement(root_ids).compile(dialect=postgresql.dialect())

    assert "files.id = ANY" in str(compiled)
    assert "RETURNING files.id" in str(compiled)
    assert set(compiled.params) == {"root_file_ids"}
    assert len(compiled.params["root_file_ids"]) == 40_000


class _Database:
    def init(self, url: str) -> None:
        pass

    @asynccontextmanager
    async def session(self):
        yield object()

    async def close(self) -> None:
        pass


class _Runner:
    async def run(self, task: object) -> str:
        return "report"


@pytest.mark.asyncio
async def test_the_cleanup_command_runs_with_its_own_redis_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`python -m eneo.files.unused_file_cleanup run` runs in a process of its
    own, so it starts the Redis clients the retention runner reads (its audit
    settings do) and stops them again."""
    from eneo.data_retention.infrastructure import retention_worker
    from eneo.database import database
    from eneo.main import retention_tasks

    reached: list[object] = []

    def runner(**kwargs: object) -> _Runner:
        reached.append(redis_clients.commands())
        return _Runner()

    registration = SimpleNamespace(
        name=UNUSED_FILES_TASK, enabled=True, budget=None, build=lambda session: None
    )
    monkeypatch.setattr(database, "DatabaseSessionManager", _Database)
    monkeypatch.setattr(retention_worker, "retention_runner", runner)
    monkeypatch.setattr(
        retention_tasks, "retention_task_registrations", lambda settings: [registration]
    )
    # A new process: nothing has started the clients yet.
    await redis_clients.stop()

    assert await unused_file_cleanup._run_from_cli(dry_run=False) == "report"

    assert len(reached) == 1
    with pytest.raises(NotReadyException):
        redis_clients.commands()
