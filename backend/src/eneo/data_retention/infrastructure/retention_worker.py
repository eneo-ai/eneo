"""Retention crons on the general worker.

The nightly cron runs every registered task, or records its skip when it is
turned off. The five-minute cron runs the enabled frequent tasks, each only
when its due probe finds work, so with nothing due it writes nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_registration import (
    RetentionTaskRegistration,
)
from eneo.data_retention.application.retention_runner import (
    RetentionChunkLimits,
    RetentionContractError,
    RetentionRunner,
    RetentionRunReport,
)
from eneo.data_retention.domain.retention import RetentionBudget
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.database.database import sessionmanager
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.main.retention_tasks import retention_task_registrations
from eneo.observability.error_log import log_error
from eneo.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()


def retention_runner(
    *,
    session: AsyncSession,
    container: Container,
    settings: Settings,
    budget: RetentionBudget,
) -> RetentionRunner:
    return RetentionRunner(
        session=session,
        job_runs=RetentionJobRunRepository(session),
        audit_service=container.audit_service(),
        budget=budget,
        limits=RetentionChunkLimits(
            rows=settings.retention_chunk_rows,
            statement_timeout_ms=settings.retention_chunk_statement_timeout_ms,
            lock_timeout_ms=settings.retention_chunk_lock_timeout_ms,
            lease_stale_seconds=settings.retention_lease_stale_seconds,
        ),
    )


_settings = get_settings()


@worker.cron_job(
    hour=_settings.retention_cron_hour,
    minute=_settings.retention_cron_minute,
    manages_own_session=True,
)
async def run_retention(container: Container) -> list[RetentionRunReport]:
    """Run each enabled task once; each task commits chunk by chunk."""
    session = container.session()
    if not isinstance(session, AsyncSession):
        raise RetentionContractError("Retention cron requires an AsyncSession.")
    return await _run_tasks(container, session, await _database_now(session))


@worker.cron_job(minute=set(range(0, 60, 5)), manages_own_session=True)
async def run_retention_frequent(container: Container) -> list[RetentionRunReport]:
    """Run each enabled frequent task whose due probe finds work.

    Which tasks are frequent and enabled is known from the settings alone, so
    without one the cron ends before it touches the database. A turned-off
    frequent task gets its skip row from the nightly cron only.
    """
    settings = get_settings()
    if not any(map(_runs_frequently, retention_task_registrations(settings))):
        return []
    session = container.session()
    if not isinstance(session, AsyncSession):
        raise RetentionContractError("Retention cron requires an AsyncSession.")
    now = await _database_now(session)
    return await run_due_tasks(
        session,
        retention_task_registrations(settings, now=now),
        lambda budget: retention_runner(
            session=session, container=container, settings=settings, budget=budget
        ),
    )


def _runs_frequently(registration: RetentionTaskRegistration) -> bool:
    return registration.every == "frequent" and registration.enabled


async def database_now() -> datetime:
    async with sessionmanager.session() as session:
        return await _database_now(session)


async def run_retention_at(now: datetime) -> list[RetentionRunReport]:
    """Run each enabled task once against a time the caller read.

    The readback after a restore runs every round against the time it
    started, so rows that fall due while it runs are left to the scheduled
    run and a busy installation does not keep it removing.
    """
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        return await _run_tasks(container, session, now)


async def _database_now(session: AsyncSession) -> datetime:
    # Due-ness follows the database's clock, read once for the whole execution,
    # so a worker whose clock is off neither removes early nor keeps late.
    async with session.begin():
        return (await session.execute(sa.select(sa.func.now()))).scalar_one()


async def _run_tasks(
    container: Container, session: AsyncSession, now: datetime
) -> list[RetentionRunReport]:
    settings = get_settings()
    return await run_registered_tasks(
        session,
        retention_task_registrations(settings, now=now),
        lambda budget: retention_runner(
            session=session, container=container, settings=settings, budget=budget
        ),
    )


async def run_registered_tasks(
    session: AsyncSession,
    registrations: Sequence[RetentionTaskRegistration],
    runner_for: Callable[[RetentionBudget], RetentionRunner],
) -> list[RetentionRunReport]:
    """Run or record every registration; one task's error does not stop the rest.

    A task that raised gets no report: its error is logged under its name, and
    an unfinished job row is left to the stale takeover.
    """

    async def run_or_skip(
        registration: RetentionTaskRegistration, runner: RetentionRunner
    ) -> RetentionRunReport:
        if registration.enabled:
            return await runner.run(registration.build(session))
        return await runner.skip(registration.name)

    return await _each(registrations, runner_for, run_or_skip)


async def run_due_tasks(
    session: AsyncSession,
    registrations: Sequence[RetentionTaskRegistration],
    runner_for: Callable[[RetentionBudget], RetentionRunner],
) -> list[RetentionRunReport]:
    """Run, in order, each enabled frequent registration whose due probe finds
    work; one task's error does not stop the rest. A task with nothing due
    gets no report. Others are not built."""

    async def run_when_due(
        registration: RetentionTaskRegistration, runner: RetentionRunner
    ) -> RetentionRunReport | None:
        return await runner.run_when_due(registration.build(session))

    return await _each(
        [
            registration
            for registration in registrations
            if _runs_frequently(registration)
        ],
        runner_for,
        run_when_due,
    )


async def _each(
    registrations: Sequence[RetentionTaskRegistration],
    runner_for: Callable[[RetentionBudget], RetentionRunner],
    start: Callable[
        [RetentionTaskRegistration, RetentionRunner],
        Awaitable[RetentionRunReport | None],
    ],
) -> list[RetentionRunReport]:
    reports: list[RetentionRunReport] = []
    for registration in registrations:
        runner = runner_for(registration.budget)
        try:
            report = await start(registration, runner)
        except Exception as exc:
            log_error(
                logger,
                logging.ERROR,
                "Retention task %s raised; continuing",
                registration.name,
                error=exc,
            )
            continue
        if report is None:
            continue
        logger.info(
            "Retention task %s finished: %s",
            report.task,
            report.outcome.value if report.outcome is not None else "claim_lost",
            extra={"counts": dict(report.counts), "blocked": dict(report.blocked)},
        )
        reports.append(report)
    return reports
