"""Stale-run timing is shared by redispatch, reconciliation, and health checks.

The running thresholds are coupled to the platform maintenance schedule for
`flows.reconcile_running`; changing the schedule must change the health policy
at the same time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TypedDict
from uuid import UUID

FLOW_QUEUED_REDISPATCH_AFTER_SECONDS = 30
FLOW_DISPATCH_MAX_ATTEMPTS = 5
FLOW_DISPATCH_RETRY_BACKOFF_SECONDS = (30, 120, 300, 900)
FLOW_TASK_HARD_TIMEOUT_MARGIN_SECONDS = 60
FLOW_EXECUTION_HEARTBEAT_INTERVAL_SECONDS = 30
FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS = 180
FLOW_EXECUTION_HEARTBEAT_MAX_FAILURES = 3
FLOW_EXECUTION_HEARTBEAT_TRANSACTION_TIMEOUT_SECONDS = 10
FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS = 60
FLOW_RUN_ABANDONMENT_AFTER = timedelta(days=30)


class FlowRunAbandonmentWait(StrEnum):
    APPROVED_REVIEW = "approved_review"
    EXHAUSTED_DISPATCH = "exhausted_dispatch"


class FlowRunRecoveryKind(StrEnum):
    EXECUTION_HEARTBEAT_EXPIRED = "execution_heartbeat_expired"
    APPROVED_REVIEW = "approved_review"
    EXHAUSTED_DISPATCH = "exhausted_dispatch"
    MISSING_REVIEW_CHECKPOINT = "missing_review_checkpoint"


def flow_run_abandonment_deadline(anchor_at: datetime) -> datetime:
    return anchor_at + FLOW_RUN_ABANDONMENT_AFTER


@dataclass(eq=False)
class FlowRunAbandonmentDeadlineExceeded(Exception):
    wait: FlowRunAbandonmentWait
    anchor_at: datetime
    checkpoint_id: UUID | None = None


def require_flow_run_wait_before_deadline(
    *,
    wait: FlowRunAbandonmentWait,
    anchor_at: datetime,
    now: datetime,
    checkpoint_id: UUID | None = None,
) -> None:
    if now >= flow_run_abandonment_deadline(anchor_at):
        raise FlowRunAbandonmentDeadlineExceeded(wait, anchor_at, checkpoint_id)


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
    return FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS


def flow_stale_running_unhealthy_after_seconds(*, task_timeout_seconds: int) -> int:
    return (
        FLOW_EXECUTION_HEARTBEAT_EXPIRY_SECONDS
        + FLOW_RUNNING_RECONCILE_INTERVAL_SECONDS
    )
