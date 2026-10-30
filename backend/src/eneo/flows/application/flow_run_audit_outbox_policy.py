from __future__ import annotations

from eneo.main.config import get_settings

FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE = 100
FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS = 60
FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS = 5
FLOW_AUDIT_OUTBOX_RETRY_BACKOFF_SECONDS = (60, 300, 900, 3600)
FLOW_AUDIT_OUTBOX_BACKLOG_GRACE_SECONDS = 300

assert (
    len(FLOW_AUDIT_OUTBOX_RETRY_BACKOFF_SECONDS) == FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS - 1
)


def flow_audit_outbox_retry_delay_seconds(*, failed_attempt_no: int) -> int | None:
    if failed_attempt_no < 1:
        raise ValueError("failed_attempt_no must be at least 1")
    if failed_attempt_no >= FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS:
        return None
    return FLOW_AUDIT_OUTBOX_RETRY_BACKOFF_SECONDS[failed_attempt_no - 1]


def flow_audit_outbox_drain_seconds() -> float:
    """How long one delivery job goes on starting batches: half the maintenance
    job timeout, which leaves the batch in flight the other half to commit
    before ARQ cancels the job, and at most half the delivery interval, so a
    job under a backlog ends before the next tick starts another one beside
    it in the maintenance worker's few slots."""
    return min(
        get_settings().task_maintenance_timeout_seconds / 2,
        FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS / 2,
    )
