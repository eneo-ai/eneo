from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.enums import FlowOutputMode
from eneo.flows.runtime.step_execution_result import (
    StepExecutionResult,
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.flows.runtime.step_handlers.base import StepHandler


@dataclass(frozen=True)
class HttpPostStepHandler:
    completion_handler: StepHandler
    output_mode: FlowOutputMode = FlowOutputMode.HTTP_POST

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
    ) -> StepExecutionResult:
        result = await self.completion_handler.execute(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            attempt_no=attempt_no,
        )
        intent = WebhookDeliveryIntent(
            flow_run_id=run.id,
            step_id=step.step_id,
            step_order=step.step_order,
            attempt_no=attempt_no,
            idempotency_key=f"{run.id}:{step.step_id}:{attempt_no}:webhook",
            payload=WebhookPayloadRef(
                value=f"flow_run:{run.id}:step:{step.step_id}:attempt:{attempt_no}"
            ),
        )
        return StepExecutionResult(
            output=result.output,
            delivery_intents=(*result.delivery_intents, intent),
        )
