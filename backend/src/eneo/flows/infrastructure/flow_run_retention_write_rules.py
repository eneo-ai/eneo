"""What a Flow run-history retention policy write may contain in this deployment.

The one owner of the write limits: the policy service validates every write
against them and the settings responses expose them, so the UI shows the same
limits the API enforces.
"""

from __future__ import annotations

from eneo.flows.domain.flow_run_retention_policy import (
    FLOWS_HISTORY_TASK,
    FlowRunRetentionWriteRules,
)
from eneo.main.config import Settings, get_settings


def flows_history_task_registered() -> bool:
    """The activation gate of auto_delete: the deleting task is in the code list
    of registered gallring tasks (its emergency switch does not matter here)."""
    # Imported here: the task registry imports flows application modules.
    from eneo.data_retention.infrastructure.retention_tasks import RETENTION_TASKS

    return any(task.name == FLOWS_HISTORY_TASK for task in RETENTION_TASKS)


def flow_run_retention_write_rules(
    settings: Settings | None = None,
) -> FlowRunRetentionWriteRules:
    settings = settings if settings is not None else get_settings()
    return FlowRunRetentionWriteRules(
        max_days=settings.flow_retention_max_days,
        auto_delete_available=flows_history_task_registered(),
    )
