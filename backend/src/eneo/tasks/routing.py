from __future__ import annotations

from dataclasses import dataclass

from eneo.main.config import Settings, get_settings
from eneo.tasks.contracts import TaskCapacityClass

FLOW_EXECUTE_TASK = "flows.execute"
FLOW_RECONCILE_RUNNING_TASK = "flows.reconcile_running"
FLOW_RECONCILE_REVIEW_EXPIRY_TASK = "flows.reconcile_review_expiry"
FLOW_REDISPATCH_STALE_QUEUED_TASK = "flows.redispatch_stale_queued"
FLOW_DELIVER_AUDIT_OUTBOX_TASK = "flows.deliver_audit_outbox"
FLOW_DELIVER_WEBHOOK_OUTBOX_TASK = "flows.deliver_webhook_outbox"


TASK_CAPACITY_BY_NAME: dict[str, TaskCapacityClass] = {
    FLOW_EXECUTE_TASK: TaskCapacityClass.EXECUTION,
    FLOW_RECONCILE_RUNNING_TASK: TaskCapacityClass.MAINTENANCE,
    FLOW_RECONCILE_REVIEW_EXPIRY_TASK: TaskCapacityClass.MAINTENANCE,
    FLOW_REDISPATCH_STALE_QUEUED_TASK: TaskCapacityClass.MAINTENANCE,
    FLOW_DELIVER_AUDIT_OUTBOX_TASK: TaskCapacityClass.MAINTENANCE,
    FLOW_DELIVER_WEBHOOK_OUTBOX_TASK: TaskCapacityClass.MAINTENANCE,
}


@dataclass(frozen=True, slots=True)
class TaskQueueRouting:
    execution_queue: str
    maintenance_queue: str

    def queue_for(self, capacity_class: TaskCapacityClass) -> str:
        if capacity_class is TaskCapacityClass.EXECUTION:
            return self.execution_queue
        return self.maintenance_queue


def task_queue_routing(settings: Settings | None = None) -> TaskQueueRouting:
    resolved = settings or get_settings()
    return TaskQueueRouting(
        execution_queue=resolved.task_execution_queue,
        maintenance_queue=resolved.task_maintenance_queue,
    )
