from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

# Where a delivery stands when read: the two states of a pending delivery,
# then its final statuses by their own names.
FlowWebhookDeliveryState = Literal[
    "sending", "retry_scheduled", "delivered", "dead_lettered"
]


@dataclass(frozen=True)
class WebhookPayloadRef:
    value: str


@dataclass(frozen=True)
class WebhookDeliveryIntent:
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    idempotency_key: str
    payload: WebhookPayloadRef
