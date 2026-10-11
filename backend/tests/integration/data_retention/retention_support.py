"""Exercise registered tasks through their production runner and committed fixtures."""

from datetime import datetime
from uuid import UUID

from dependency_injector import providers
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.action_types import ActionType
from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.domain.retention import RetentionErrorCode
from eneo.data_retention.infrastructure.retention_worker import retention_runner
from eneo.database.tables.audit_log_table import AuditLog
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.main.retention_tasks import retention_task_registrations


async def run_registered_retention(
    session: AsyncSession,
    *,
    task_name: str = "conversations.history",
    settings: Settings | None = None,
    now: datetime | None = None,
    error_code: RetentionErrorCode | None = None,
) -> RetentionRunReport:
    if session.in_transaction():
        await session.commit()
    configured = settings if settings is not None else get_settings()
    registration = next(
        task
        for task in retention_task_registrations(configured, now=now)
        if task.name == task_name
    )
    report = await retention_runner(
        session=session,
        container=Container(session=providers.Object(session)),
        settings=configured,
        budget=registration.budget,
    ).run(registration.build(session))
    assert report.error_code is error_code, report
    session.expunge_all()
    await session.begin()
    return report


async def step_batches(
    session: AsyncSession, job_run_id: UUID | None, step: str
) -> list[dict[str, object]]:
    """The metadata of one step's batch audit events in one execution, in order."""
    return list(
        await session.scalars(
            select(AuditLog.log_metadata)
            .where(
                AuditLog.action == ActionType.DATA_RETENTION_BATCH.value,
                AuditLog.log_metadata["job_run_id"].astext == str(job_run_id),
                AuditLog.log_metadata["step"].astext == step,
            )
            .order_by(AuditLog.log_metadata["batch_seq"].as_integer())
        )
    )
