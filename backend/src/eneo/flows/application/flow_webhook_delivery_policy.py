from __future__ import annotations

from eneo.audit.domain.constants import MAX_ERROR_MESSAGE_LENGTH
from eneo.flows.flow_run_redaction import redact_string

FLOW_WEBHOOK_DELIVERY_INTERVAL_SECONDS = 30
FLOW_WEBHOOK_DELIVERY_BATCH_SIZE = 50
FLOW_WEBHOOK_DELIVERY_CLAIM_TTL_SECONDS = 300
FLOW_WEBHOOK_MAX_ATTEMPTS = 5
FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS = (30, 120, 300, 900)

assert len(FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS) == FLOW_WEBHOOK_MAX_ATTEMPTS - 1


def flow_webhook_retry_delay_seconds(*, failed_attempt_no: int) -> int | None:
    if failed_attempt_no < 1:
        raise ValueError("failed_attempt_no must be at least 1")
    if failed_attempt_no >= FLOW_WEBHOOK_MAX_ATTEMPTS:
        return None
    return FLOW_WEBHOOK_RETRY_BACKOFF_SECONDS[failed_attempt_no - 1]


def sanitize_webhook_delivery_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    if not message:
        message = error.__class__.__name__
    message = redact_string(message, key=None)
    return f"{error.__class__.__name__}: {message}"[:MAX_ERROR_MESSAGE_LENGTH]
