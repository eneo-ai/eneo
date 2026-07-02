"""Stale-run timing is shared by redispatch, reconciliation, and health checks.

The running thresholds are coupled to the Celery beat schedule for
`flows.reconcile_running`; changing the schedule must change the health policy
at the same time.
"""

from __future__ import annotations

FLOW_QUEUED_REDISPATCH_AFTER_SECONDS = 30
FLOW_TASK_HARD_TIMEOUT_MARGIN_SECONDS = 60
FLOW_RUNNING_RECONCILE_GRACE_SECONDS = 60
FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS = 60
FLOW_RUNNING_RECONCILE_UNHEALTHY_AFTER_INTERVALS = 2


def flow_task_hard_timeout_seconds(*, task_timeout_seconds: int) -> int:
    return max(int(task_timeout_seconds), 1) + FLOW_TASK_HARD_TIMEOUT_MARGIN_SECONDS


def flow_stale_running_reconcile_after_seconds(*, task_timeout_seconds: int) -> int:
    return max(int(task_timeout_seconds), 1) + FLOW_RUNNING_RECONCILE_GRACE_SECONDS


def flow_stale_running_unhealthy_after_seconds(*, task_timeout_seconds: int) -> int:
    return flow_stale_running_reconcile_after_seconds(
        task_timeout_seconds=task_timeout_seconds
    ) + (
        FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS
        * FLOW_RUNNING_RECONCILE_UNHEALTHY_AFTER_INTERVALS
    )
