from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from eneo.flows.domain.runtime import StepExecutionOutput


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


@dataclass(frozen=True)
class StepExecutionResult:
    output: StepExecutionOutput
    delivery_intents: tuple[WebhookDeliveryIntent, ...] = ()
