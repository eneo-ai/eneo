"""Run registered adopters with committed fixtures and the production worker factory."""

from datetime import datetime

from dependency_injector import providers
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.infrastructure.retention_tasks import (
    CONVERSATION_HISTORY_TASK,
    RETENTION_TASKS,
    build_conversation_history_task,
)
from eneo.data_retention.infrastructure.retention_worker import retention_runner
from eneo.main.config import get_settings
from eneo.main.container.container import Container


async def run_conversation_history(
    session: AsyncSession, *, now: datetime | None = None
) -> RetentionRunReport:
    if session.in_transaction():
        await session.commit()
    settings = get_settings()
    registration = next(
        task for task in RETENTION_TASKS if task.name == CONVERSATION_HISTORY_TASK
    )
    budget = registration.budget(settings)
    task = build_conversation_history_task(session, budget, settings, now=now)
    report = await retention_runner(
        session=session,
        container=Container(session=providers.Object(session)),
        settings=settings,
        budget=budget,
    ).run(task)
    session.expunge_all()
    await session.begin()
    return report
