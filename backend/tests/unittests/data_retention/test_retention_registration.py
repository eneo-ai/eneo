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
from eneo.data_retention.application.retention_registration import (
    retention_registration_violations,
)
from eneo.data_retention.domain.rules import (
    RETENTION_RULES,
    RetentionRule,
    RuleExemption,
)
from eneo.database import database
from eneo.database.database import DatabaseSessionManager
from eneo.main.config import Settings, get_settings
from eneo.main.retention_tasks import (
    EXISTING_WITHOUT_CHOICE,
    RetentionHealthCache,
    _read_retention_health,
    retention_task_registrations,
)


def test_retention_cron_is_registered():
    """Mutant: the general worker does not include the retention cron."""
    from eneo.worker.arq import worker

    assert "run_retention" in {job.coroutine.__name__ for job in worker.cron_jobs}


def test_registered_tasks_replace_the_removal_crons():
    """Mutants: a cron that deleted conversations, empty sessions or unused files
    runs again beside the task that replaced it; the widget's own nightly job,
    which the engine leaves widget conversations to, is dropped."""
    from eneo.worker.arq import worker

    crons = {job.coroutine.__name__ for job in worker.cron_jobs}
    registered = {
        registration.name
        for registration in retention_task_registrations(get_settings())
    }

    assert crons.isdisjoint(
        {"cleanup_old_data", "purge_old_conversations", "delete_unused_files"}
    )
    assert "purge_widget_sessions" in crons
    assert registered == {
        "conversations.history",
        "sessions.empty",
        "files.unused",
        "retention.jobs",
    }


def test_only_listed_removals_run_without_a_choice():
    """Mutants: a new task is on by default without being listed among the
    removals that run without a choice; a listed removal loses its operator
    switch, or its default changes."""
    defaults = Settings.model_fields
    on_by_default = {
        registration.name
        for registration in retention_task_registrations(get_settings())
        if registration.enabled
    }

    # Conversation history removes only what an assistant, app, space or
    # organisation period selects; with none set it keeps everything.
    assert on_by_default == {"conversations.history", *EXISTING_WITHOUT_CHOICE}
    for task, switch in EXISTING_WITHOUT_CHOICE.items():
        assert defaults[switch].default is True
        switched_off = get_settings().model_copy(update={switch: False})
        assert [
            registration.enabled
            for registration in retention_task_registrations(switched_off)
            if registration.name == task
        ] == [False]


def _violations(**changes: object) -> list[str]:
    declared: dict[str, object] = {
        "vocabulary": tuple(RetentionRule),
        "rules": RETENTION_RULES,
        "registered": [
            registration.name
            for registration in retention_task_registrations(get_settings())
        ],
        "existing_without_choice": EXISTING_WITHOUT_CHOICE,
        "settings": Settings.model_fields,
    }
    declared.update(changes)
    return retention_registration_violations(**declared)  # type: ignore[arg-type]


def test_every_rule_and_every_registered_task_is_declared():
    """The platform's own declaration passes: each rule has a task or an
    exemption, and each task removes a rule's roots or is listed with its
    switch."""
    assert _violations() == []


def test_the_registration_check_fails_on_each_omission():
    """Mutants, one per check: a rule without a disposition; a disposition
    outside the vocabulary; a rule whose task is not registered; a task that
    is neither a rule's nor listed; a listed task that is not registered; a
    listed switch that is no setting; a rule's task also listed as running
    without a choice."""
    registered = [
        registration.name
        for registration in retention_task_registrations(get_settings())
    ]
    omissions = {
        "rule without disposition": {
            "vocabulary": (*RetentionRule, "unlisted_rule"),
        },
        "disposition outside the vocabulary": {
            "rules": {**RETENTION_RULES, "stray_rule": RuleExemption("stray")},
        },
        "rule task not registered": {
            "registered": [
                name for name in registered if name != "conversations.history"
            ],
        },
        "task in no list": {"registered": [*registered, "files.everything"]},
        "listed task that is not registered": {
            "existing_without_choice": {
                **EXISTING_WITHOUT_CHOICE,
                "sessions.gone": "retention_empty_sessions_enabled",
            },
        },
        "switch that is no setting": {
            "existing_without_choice": {
                **EXISTING_WITHOUT_CHOICE,
                "sessions.empty": "retention_no_such_switch",
            },
        },
        "rule task listed as without a choice": {
            "existing_without_choice": {
                **EXISTING_WITHOUT_CHOICE,
                "conversations.history": "retention_conversations_history_enabled",
            },
        },
    }
    for omission, changes in omissions.items():
        assert len(_violations(**changes)) == 1, omission


def test_a_rule_with_an_exemption_needs_no_task():
    """Mutant: an exempt rule is required to have a registered task, so a rule
    removed outside the engine cannot be declared honestly."""
    assert (
        _violations(
            vocabulary=(*RetentionRule, "kept_by_its_owner"),
            rules={**RETENTION_RULES, "kept_by_its_owner": RuleExemption("owner")},
        )
        == []
    )


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
