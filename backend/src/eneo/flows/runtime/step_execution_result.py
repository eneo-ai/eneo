from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain import flow_webhook_delivery
from eneo.flows.domain.runtime import StepExecutionOutput


@dataclass(frozen=True)
class StepExecutionResult:
    output: StepExecutionOutput
    delivery_intents: tuple[flow_webhook_delivery.WebhookDeliveryIntent, ...] = ()
