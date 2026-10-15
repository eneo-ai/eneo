from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.output_modes import compose_text_violation
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import attach_typed_failure_context
from eneo.flows.runtime.step_handlers.base import PrepareAssistantStepFn
from eneo.flows.runtime.step_handlers.deterministic_result import deterministic_result
from eneo.main.exceptions import TypedIOValidationException


@dataclass(frozen=True)
class ComposeTextStepHandler:
    prepare_assistant_step: PrepareAssistantStepFn
    output_mode: FlowOutputMode = FlowOutputMode.COMPOSE_TEXT

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
    ) -> StepExecutionResult:
        prepared_step = await self.prepare_assistant_step(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            attempt_no=attempt_no,
        )
        prepared = prepared_step.prepared
        deps = prepared_step.deps
        mode_error = compose_text_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if mode_error is not None:
            raise attach_typed_failure_context(
                TypedIOValidationException(
                    mode_error,
                    code=FlowApiErrorCode.TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION.value,
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt="",
            )

        try:
            typed_output = await deps.process_typed_output(
                full_text=prepared.step_input.text,
                step=step,
                run=run,
            )
        except TypedIOValidationException as exc:
            raise attach_typed_failure_context(
                exc,
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt="",
            ) from exc

        output_text = typed_output.persisted_text(prepared.step_input.text)
        persisted_text, generated_file_ids = await deps.apply_output_cap(
            text=output_text,
            run=run,
            step=step,
        )
        return deterministic_result(
            prepared=prepared,
            typed_output=typed_output,
            output_text=output_text,
            persisted_text=persisted_text,
            generated_file_ids=generated_file_ids,
            mode=self.output_mode,
            diagnostic=StepDiagnostic(
                code="compose_text_used",
                message=(
                    f"Step {step.step_order}: compose_text mode persisted resolved "
                    "text without calling the assistant."
                ),
                severity="info",
            ),
        )
