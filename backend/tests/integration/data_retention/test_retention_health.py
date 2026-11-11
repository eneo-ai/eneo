"""Health of the registered tasks as the API reads it after the worker's nightly
run, with the composition root's registrations and each process's own settings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from eneo.data_retention.application.conversation_history_retention_task import (
    CONVERSATION_HISTORY_TASK,
)
from eneo.data_retention.application.empty_session_retention_task import (
    EMPTY_SESSIONS_TASK,
)
from eneo.data_retention.application.retention_health import (
    RetentionHealth,
    RetentionHealthStatus,
)
from eneo.data_retention.domain.retention import (
    RetentionErrorCode,
    RetentionJobOutcome,
)
from eneo.data_retention.infrastructure.retention_worker import (
    database_now,
    run_retention_at,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.retention_tables import RetentionJobRuns
from eneo.main.config import Settings, get_settings
from eneo.main.retention_tasks import (
    EXISTING_WITHOUT_CHOICE,
    FOLLOWS_A_REMOVAL,
    _read_retention_health,
    retention_task_registrations,
)
from tests.integration.data_retention.retention_support import run_nightly_retention

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

HEALTHY = RetentionHealthStatus.HEALTHY

# Every registered task with the setting that switches it off.
SWITCHES = {
    CONVERSATION_HISTORY_TASK: "retention_conversations_history_enabled",
    **FOLLOWS_A_REMOVAL,
    **EXISTING_WITHOUT_CHOICE,
}


def _switched_off(task: str) -> Settings:
    return get_settings().model_copy(update={SWITCHES[task]: False})


def _tasks(health: RetentionHealth) -> dict[str, tuple[RetentionHealthStatus, bool]]:
    return {task.name: (task.status, task.disabled) for task in health.tasks}


async def test_every_registration_has_a_switch():
    """Mutant: a task is registered without the switch these tests turn off."""
    assert [
        registration.name
        for registration in retention_task_registrations(get_settings())
    ] == list(SWITCHES)


async def test_a_default_night_reads_healthy(monkeypatch: pytest.MonkeyPatch):
    """Mutant: a task the default settings run reads anything but healthy after
    a night with nothing due."""
    await run_nightly_retention(monkeypatch, get_settings())

    health = await _read_retention_health(get_settings())

    assert health.status is HEALTHY
    assert _tasks(health) == {task: (HEALTHY, False) for task in SWITCHES}


@pytest.mark.parametrize("task", list(SWITCHES))
async def test_a_task_the_worker_has_switched_off_does_not_degrade_health(
    monkeypatch: pytest.MonkeyPatch, task: str
):
    """Mutants: a task the operator switched off in the worker degrades the
    overall health, or reads healthy instead of disabled while the API process
    has it on."""
    await run_nightly_retention(monkeypatch, _switched_off(task))

    health = await _read_retention_health(get_settings())

    assert health.status is HEALTHY
    assert _tasks(health) == {
        name: (
            (RetentionHealthStatus.DISABLED, True) if name == task else (HEALTHY, False)
        )
        for name in SWITCHES
    }


async def test_the_worker_decides_once_a_task_has_run(
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutant: the API process's setting overrides the worker's latest run, so a
    task the worker ran reads disabled."""
    await run_nightly_retention(monkeypatch, get_settings())

    health = await _read_retention_health(_switched_off(EMPTY_SESSIONS_TASK))

    assert health.status is HEALTHY
    assert _tasks(health)[EMPTY_SESSIONS_TASK] == (HEALTHY, False)


async def test_before_any_run_the_api_setting_reads_disabled():
    """Mutant: a task the API process has switched off degrades health before
    the worker ran once, instead of reading disabled beside initializing tasks."""
    health = await _read_retention_health(_switched_off(EMPTY_SESSIONS_TASK))

    assert health.status is RetentionHealthStatus.INITIALIZING
    [disabled] = [task for task in health.tasks if task.disabled]
    assert (disabled.name, disabled.status, disabled.no_execution) == (
        EMPTY_SESSIONS_TASK,
        RetentionHealthStatus.DISABLED,
        True,
    )
    assert {task.status for task in health.tasks if not task.disabled} == {
        RetentionHealthStatus.INITIALIZING
    }


async def test_a_failed_task_degrades_health_beside_a_disabled_one(
    monkeypatch: pytest.MonkeyPatch,
):
    """Mutant: ignoring disabled tasks also hides the failure of an enabled one."""
    await run_nightly_retention(monkeypatch, _switched_off(EMPTY_SESSIONS_TASK))
    later = datetime.now(timezone.utc) + timedelta(seconds=1)
    async with sessionmanager.session() as session, session.begin():
        session.add(
            RetentionJobRuns(
                task=CONVERSATION_HISTORY_TASK,
                outcome=RetentionJobOutcome.FAILED.value,
                started_at=later,
                heartbeat_at=later,
                finished_at=later,
                error_code=RetentionErrorCode.CHUNK_FAILED.value,
            )
        )

    health = await _read_retention_health(get_settings())

    assert health.status is RetentionHealthStatus.DEGRADED
    tasks = {task.name: task for task in health.tasks}
    history = tasks[CONVERSATION_HISTORY_TASK]
    assert (history.status, history.failed) == (RetentionHealthStatus.DEGRADED, True)
    assert _tasks(health)[EMPTY_SESSIONS_TASK] == (RetentionHealthStatus.DISABLED, True)


async def test_every_way_to_run_retention_measures_overdue_work(
    monkeypatch: pytest.MonkeyPatch,
):
    """The scheduled run and the readback's rounds both end a task with its
    overdue work measured, so a completed run without a measurement means the
    read failed.

    Mutant: a path finishes a run without trying to measure it."""
    await run_nightly_retention(monkeypatch, get_settings())
    await run_retention_at(await database_now())

    async with sessionmanager.session() as session, session.begin():
        observed = (
            await session.scalars(
                sa.select(RetentionJobRuns.overdue_observed_at)
                .where(RetentionJobRuns.task == CONVERSATION_HISTORY_TASK)
                .order_by(RetentionJobRuns.started_at)
            )
        ).all()

    assert len(observed) == 2
    assert None not in observed
