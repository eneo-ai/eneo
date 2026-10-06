from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


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
