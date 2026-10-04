"""Nightly gallring cron on the general worker: runs every enabled registered task."""

from __future__ import annotations

import logging
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.gallring_runner import (
    GallringChunkLimits,
    GallringRunner,
    GallringRunReport,
)
from eneo.data_retention.domain.gallring import GallringBudget
from eneo.data_retention.infrastructure.gallring_job_run_repo import (
    GallringJobRunRepository,
)
from eneo.data_retention.infrastructure.gallring_tasks import GALLRING_TASKS
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.worker.worker import Worker

logger = logging.getLogger(__name__)
worker = Worker()


def gallring_runner(
    *, session: AsyncSession, container: Container, settings: Settings
) -> GallringRunner:
    return GallringRunner(
        session=session,
        job_runs=GallringJobRunRepository(session),
        audit_service=container.audit_service(),
        budget=GallringBudget(
            rows=settings.gallring_max_rows_per_run,
            files=settings.gallring_max_files_per_run,
            seconds=settings.gallring_max_seconds_per_run,
        ),
        limits=GallringChunkLimits(
            rows=settings.gallring_chunk_rows,
            statement_timeout_ms=settings.gallring_chunk_statement_timeout_ms,
            lock_timeout_ms=settings.gallring_chunk_lock_timeout_ms,
            stale_after_seconds=settings.gallring_stale_after_seconds,
        ),
    )


_settings = get_settings()


@worker.cron_job(
    hour=_settings.gallring_cron_hour,
    minute=_settings.gallring_cron_minute,
    manages_own_session=True,
)
async def run_gallring(container: Container) -> list[GallringRunReport]:
    """Run each enabled task once; each task commits chunk by chunk."""
    settings = get_settings()
    session = cast(AsyncSession, container.session())
    runner = gallring_runner(session=session, container=container, settings=settings)
    reports: list[GallringRunReport] = []
    for registration in GALLRING_TASKS:
        if registration.enabled(settings):
            report = await runner.run(registration.build(session))
        else:
            report = await runner.skip(registration.name)
        logger.info(
            "Gallring task %s finished: %s",
            report.task,
            report.outcome.value if report.outcome is not None else "claim_lost",
            extra={"counts": dict(report.counts), "blocked": dict(report.blocked)},
        )
        reports.append(report)
    return reports
