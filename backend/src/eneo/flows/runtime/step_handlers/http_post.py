from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.flow_webhook_delivery import (
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.http_transport import sends_run_result
from eneo.flows.runtime.step_execution_result import StepExecutionResult
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
        if sends_run_result(step.output_mode, step.output_config):
            # The run's result is built from its deliverables once the run
            # has completed; the step reads nothing and holds no content.
            output = _run_result_output(step)
            delivery_intents = ()
        else:
            result = await self.completion_handler.execute(
                step=step,
                run=run,
                state=state,
                version_metadata=version_metadata,
                attempt_no=attempt_no,
            )
            output, delivery_intents = result.output, result.delivery_intents
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
            output=output,
            delivery_intents=(*delivery_intents, intent),
        )


def _run_result_output(step: RuntimeStep) -> StepExecutionOutput:
    return StepExecutionOutput(
        input_text="",
        source_text="",
        input_source=step.input_source,
        used_question_binding=False,
        full_text="",
        persisted_text="",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=0,
        num_tokens_output=0,
        effective_prompt="",
        model_parameters_json={"mode": FlowOutputMode.HTTP_POST.value},
        diagnostics=[
            StepDiagnostic(
                code="run_result_sent_after_run",
                message=(
                    f"Step {step.step_order}: sends the run's result once the "
                    "run has completed; the step holds no content of its own."
                ),
                severity="info",
            )
        ],
    )
