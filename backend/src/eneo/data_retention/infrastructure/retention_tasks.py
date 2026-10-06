"""The registered retention tasks (a code list), in run order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_history_retention_task import (
    CONVERSATION_HISTORY_TASK,
    ConversationHistoryRetentionTask,
)
from eneo.data_retention.application.conversation_retention import (
    conversation_page_allocation,
)
from eneo.data_retention.application.retention_runner import RetentionTask
from eneo.data_retention.domain.retention import RetentionBudget
from eneo.flows.application.builder_client_error_retention_task import (
    BUILDER_CLIENT_ERROR_TASK,
    BuilderClientErrorRetentionTask,
)
from eneo.flows.application.flow_housekeeping_task import (
    FLOWS_HOUSEKEEPING_TASK,
    FlowHousekeepingTask,
)
from eneo.flows.application.flow_run_history_retention_task import (
    FlowRunHistoryRetentionTask,
)
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK
from eneo.main.config import Settings


@dataclass(frozen=True, slots=True)
class RetentionTaskRegistration:
    name: str
    enabled: Callable[[Settings], bool]
    build: Callable[[AsyncSession, RetentionBudget, Settings], RetentionTask]
    budget_rows: Callable[[Settings], int] = (
        lambda settings: settings.retention_max_rows_per_run
    )

    reports_overdue: bool = False

    def budget(self, settings: Settings) -> RetentionBudget:
        return RetentionBudget(
            rows=self.budget_rows(settings),
            files=settings.retention_max_files_per_run,
            seconds=settings.retention_max_seconds_per_run,
        )


def build_conversation_history_task(
    session: AsyncSession,
    budget: RetentionBudget,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> ConversationHistoryRetentionTask:
    return ConversationHistoryRetentionTask(
        session,
        allocation=conversation_page_allocation(
            unit_rows=settings.retention_chats_max_unit_rows,
            chunk_rows=settings.retention_chunk_rows,
            execution_rows=budget.rows,
        ),
        now=now if now is not None else datetime.now(timezone.utc),
        overdue_window=timedelta(days=settings.retention_overdue_window_days),
        overdue_rows=settings.retention_overdue_max_rows,
    )


# The registered tasks, in run order. Registering flows.history is what makes
# auto_delete policies acceptable (flow_run_retention_write_rules).
RETENTION_TASKS: tuple[RetentionTaskRegistration, ...] = (
    RetentionTaskRegistration(
        name=FLOWS_HOUSEKEEPING_TASK,
        enabled=lambda settings: settings.retention_flows_housekeeping_enabled,
        build=lambda session, _budget, settings: FlowHousekeepingTask(
            session, settings=settings
        ),
    ),
    RetentionTaskRegistration(
        name=FLOWS_HISTORY_TASK,
        reports_overdue=True,
        enabled=lambda settings: settings.retention_flows_history_enabled,
        build=lambda session, _budget, settings: FlowRunHistoryRetentionTask(
            session, settings=settings
        ),
    ),
    RetentionTaskRegistration(
        name=CONVERSATION_HISTORY_TASK,
        reports_overdue=True,
        enabled=lambda settings: settings.retention_chats_history_enabled,
        build=build_conversation_history_task,
        budget_rows=lambda settings: settings.retention_chats_max_rows_per_run,
    ),
    RetentionTaskRegistration(
        name=BUILDER_CLIENT_ERROR_TASK,
        enabled=lambda settings: settings.retention_builder_client_errors_enabled,
        build=lambda session, _budget, _settings: BuilderClientErrorRetentionTask(
            session, now=datetime.now(timezone.utc)
        ),
    ),
)


def enabled_retention_tasks(settings: Settings) -> tuple[str, ...]:
    return tuple(task.name for task in RETENTION_TASKS if task.enabled(settings))


def disabled_retention_tasks(settings: Settings) -> tuple[str, ...]:
    """Tasks the deployment's emergency switch turns off."""
    return tuple(task.name for task in RETENTION_TASKS if not task.enabled(settings))


def overdue_retention_tasks(settings: Settings) -> tuple[str, ...]:
    """Enabled tasks whose persisted overdue snapshots health must read."""
    return tuple(
        task.name
        for task in RETENTION_TASKS
        if task.enabled(settings) and task.reports_overdue
    )
