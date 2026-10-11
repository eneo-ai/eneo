"""Exercise registered tasks through their production runner and committed fixtures."""

from datetime import datetime

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.infrastructure.retention_worker import retention_runner
from eneo.main.config import Settings, get_settings
from eneo.main.container.container import Container
from eneo.main.retention_tasks import retention_task_registrations


async def run_registered_retention(
    session: AsyncSession,
    *,
    task_name: str = "conversations.history",
    settings: Settings | None = None,
    now: datetime | None = None,
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
    assert report.error_code is None, report
    session.expunge_all()
    await session.begin()
    return report
