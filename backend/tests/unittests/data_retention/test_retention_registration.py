"""The composition root's task list, its settings floors and its health cache."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_health import (
    RetentionHealth,
    RetentionHealthStatus,
)
from eneo.database import database
from eneo.database.database import DatabaseSessionManager
from eneo.main.config import Settings, get_settings
from eneo.main.retention_tasks import (
    RetentionHealthCache,
    _read_retention_health,
    retention_task_registrations,
)


def test_retention_cron_is_registered():
    """Mutant: the general worker does not include the retention cron."""
    from eneo.worker.arq import worker

    assert "run_retention" in {job.coroutine.__name__ for job in worker.cron_jobs}


def test_registrations_match_their_tasks():
    """Mutant: a registration's name disagrees with its task, so health reads a
    task that never writes a row (unknown forever)."""
    for registration in retention_task_registrations(get_settings()):
        assert registration.name == registration.build(AsyncSession()).name


@pytest.mark.parametrize(
    "setting,value,valid",
    [
        ("retention_max_family_rows", 2, False),
        ("retention_max_family_rows", 3, True),
        ("retention_chunk_rows", 3, False),
        ("retention_chunk_rows", 4, True),
        ("retention_conversations_max_unit_rows", 3, False),
        ("retention_conversations_max_unit_rows", 4, True),
        # The default family cap of 5000 rows needs ceil(5000 / 3) files.
        ("retention_max_files_per_run", 1666, False),
        ("retention_max_files_per_run", 1667, True),
    ],
)
def test_unit_floors_admit_the_minimum_complete_unit(
    setting: str, value: int, valid: bool
):
    """Mutants: accept a family cap that cannot lock, prove and delete one File,
    a chunk below four rows, where a step reserving rows // 4 defers forever,
    a unit cap below a question's four rows with a session and its helper, or
    a family cap that admits a family larger than the file budget (refused as
    insufficient_budget every pass instead of family_exceeds_budget)."""
    values = get_settings().model_dump()
    values[setting] = value
    if valid:
        assert getattr(Settings.model_validate(values), setting) == value
    else:
        with pytest.raises(ValidationError):
            Settings.model_validate(values)


async def test_health_cache_reads_once_per_window():
    """Mutant: the cache or its single flight is dropped, so every public probe
    reads the job history."""
    now = [0.0]
    reads: list[float] = []
    release = asyncio.Event()

    async def read(settings: Settings) -> RetentionHealth:
        reads.append(now[0])
        await release.wait()
        return RetentionHealth(status=RetentionHealthStatus.HEALTHY)

    health = RetentionHealthCache(read, clock=lambda: now[0])
    settings = get_settings()
    waiting = [asyncio.create_task(health(settings)) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()
    assert {result.status for result in await asyncio.gather(*waiting)} == {
        RetentionHealthStatus.HEALTHY
    }
    assert reads == [0.0]

    now[0] = settings.retention_health_cache_seconds - 0.001
    await health(settings)
    now[0] = settings.retention_health_cache_seconds
    await health(settings)
    assert reads == [0.0, settings.retention_health_cache_seconds]


class _RefusedDatabase(DatabaseSessionManager):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession]:
        self.attempts += 1
        raise OSError("test PostgreSQL outage")
        yield AsyncSession()


async def test_health_reports_a_refused_connection_as_unknown_once_per_window(
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutants: a refused connection (OSError) escapes the health read and turns
    /api/healthz into a 500; the outage is not cached, so every probe reconnects."""
    refused = _RefusedDatabase()
    monkeypatch.setattr(database, "sessionmanager", refused)
    health = RetentionHealthCache(_read_retention_health, clock=lambda: 0.0)
    settings = get_settings()

    first = await health(settings)
    second = await health(settings)

    assert first.status is second.status is RetentionHealthStatus.UNKNOWN
    assert refused.attempts == 1
