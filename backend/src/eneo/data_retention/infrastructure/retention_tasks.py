"""The registered retention tasks (a code list), in run order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import RetentionTask
from eneo.data_retention.domain.retention import RetentionBudget
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
    build: Callable[[AsyncSession, RetentionBudget], RetentionTask]
    budget_rows: Callable[[Settings], int] = (
        lambda settings: settings.gallring_max_rows_per_run
    )

    reports_overdue: bool = False

    def budget(self, settings: Settings) -> RetentionBudget:
        return RetentionBudget(
            rows=self.budget_rows(settings),
            files=settings.gallring_max_files_per_run,
            seconds=settings.gallring_max_seconds_per_run,
        )


# The registered tasks, in run order. Registering flows.history is what makes
# auto_delete policies acceptable (flow_run_retention_write_rules).
RETENTION_TASKS: tuple[RetentionTaskRegistration, ...] = (
    RetentionTaskRegistration(
        name=FLOWS_HOUSEKEEPING_TASK,
        enabled=lambda settings: settings.gallring_flows_housekeeping_enabled,
        build=lambda session, _budget: FlowHousekeepingTask(session),
    ),
    RetentionTaskRegistration(
        name=FLOWS_HISTORY_TASK,
        reports_overdue=True,
        enabled=lambda settings: settings.retention_flows_history_enabled,
        build=lambda session, _budget: FlowRunHistoryRetentionTask(session),
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
