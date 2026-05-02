from __future__ import annotations

FLOW_AUDIT_OUTBOX_DELIVERY_INTERVAL_SECONDS = 60
FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE = 100
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
