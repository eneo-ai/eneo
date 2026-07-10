"""Stale-run timing is shared by redispatch, reconciliation, and health checks.

The running thresholds are coupled to the Celery beat schedule for
`flows.reconcile_running`; changing the schedule must change the health policy
at the same time.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

FLOW_QUEUED_REDISPATCH_AFTER_SECONDS = 30
FLOW_DISPATCH_MAX_ATTEMPTS = 5
FLOW_DISPATCH_RETRY_BACKOFF_SECONDS = (30, 120, 300, 900)
FLOW_TASK_HARD_TIMEOUT_MARGIN_SECONDS = 60
FLOW_RUNNING_RECONCILE_GRACE_SECONDS = 60
FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS = 60
FLOW_RUNNING_RECONCILE_UNHEALTHY_AFTER_INTERVALS = 2

assert len(FLOW_DISPATCH_RETRY_BACKOFF_SECONDS) == FLOW_DISPATCH_MAX_ATTEMPTS - 1


class FlowDispatchEpochValues(TypedDict):
    dispatch_pending_since: datetime
    dispatch_attempt_count: int
    dispatch_last_attempt_at: None
    dispatch_last_error: None
    dispatch_next_attempt_at: datetime
    dispatched_at: None
    dispatch_exhausted_at: None


def start_flow_dispatch_epoch(now: datetime) -> FlowDispatchEpochValues:
    return {
        "dispatch_pending_since": now,
        "dispatch_attempt_count": 0,
        "dispatch_last_attempt_at": None,
        "dispatch_last_error": None,
        "dispatch_next_attempt_at": now,
        "dispatched_at": None,
        "dispatch_exhausted_at": None,
    }


def flow_dispatch_retry_delay_seconds(*, attempt_no: int) -> int:
    if attempt_no < 1 or attempt_no > FLOW_DISPATCH_MAX_ATTEMPTS:
        raise ValueError("dispatch attempt number is outside the bounded policy")
    if attempt_no == FLOW_DISPATCH_MAX_ATTEMPTS:
        return FLOW_DISPATCH_RETRY_BACKOFF_SECONDS[-1]
    return FLOW_DISPATCH_RETRY_BACKOFF_SECONDS[attempt_no - 1]


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
