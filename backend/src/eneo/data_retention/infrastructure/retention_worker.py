"""Nightly retention cron on the general worker: runs every enabled registered task."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

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
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.main.retention_tasks import retention_task_registrations
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
    settings = get_settings()
    session = container.session()
    if not isinstance(session, AsyncSession):
        raise RetentionContractError("Retention cron requires an AsyncSession.")
    return await run_registered_tasks(
        session,
        retention_task_registrations(settings),
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
    reports: list[RetentionRunReport] = []
    for registration in registrations:
        runner = runner_for(registration.budget)
        try:
            if registration.enabled:
                report = await runner.run(registration.build(session))
            else:
                report = await runner.skip(registration.name)
        except Exception:
            logger.exception("Retention task %s raised; continuing.", registration.name)
            continue
        logger.info(
            "Retention task %s finished: %s",
            report.task,
            report.outcome.value if report.outcome is not None else "claim_lost",
            extra={"counts": dict(report.counts), "blocked": dict(report.blocked)},
        )
        reports.append(report)
    return reports
