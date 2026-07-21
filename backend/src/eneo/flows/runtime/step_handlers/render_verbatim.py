from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import (
    RunExecutionState,
    RuntimeStep,
    StepDiagnostic,
    StepExecutionOutput,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.output_modes import render_verbatim_violation
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_handlers.base import PrepareAssistantStepFn
from eneo.main.exceptions import TypedIOValidationException


@dataclass(frozen=True)
class RenderVerbatimStepHandler:
    prepare_assistant_step: PrepareAssistantStepFn
    output_mode: FlowOutputMode = FlowOutputMode.RENDER_VERBATIM

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
        mode_error = render_verbatim_violation(
            step_order=step.step_order,
            input_type=step.input_type,
            output_type=step.output_type,
            output_mode=step.output_mode,
        )
        if mode_error is not None:
            raise deps.attach_typed_failure_context(
                TypedIOValidationException(
                    mode_error,
                    code=FlowApiErrorCode.TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION.value,
                ),
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=prepared.effective_prompt,
            )

        try:
            typed_output = await deps.process_typed_output(
                full_text=prepared.step_input.text,
                step=step,
                run=run,
            )
        except TypedIOValidationException as exc:
            raise deps.attach_typed_failure_context(
                exc,
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt=prepared.effective_prompt,
            ) from exc

        persisted_text, generated_file_ids = await deps.apply_output_cap(
            text=prepared.step_input.text,
            run=run,
            step=step,
        )
        diagnostics = [
            *prepared.diagnostics,
            *typed_output.diagnostics,
            StepDiagnostic(
                code="render_verbatim_used",
                message=(
                    f"Step {step.step_order}: render_verbatim mode rendered "
                    "resolved text without calling the assistant."
                ),
                severity="info",
            ),
        ]
        return StepExecutionResult(
            output=StepExecutionOutput(
                input_text=prepared.step_input.text,
                source_text=prepared.step_input.source_text,
                input_source=prepared.step_input.input_source,
                used_question_binding=prepared.step_input.used_question_binding,
                full_text=prepared.step_input.text,
                persisted_text=persisted_text,
                generated_file_ids=generated_file_ids,
                tool_calls_metadata=None,
                num_tokens_input=0,
                num_tokens_output=0,
                effective_prompt="",
                model_parameters_json={"mode": "render_verbatim"},
                contract_validation=prepared.contract_validation,
                structured_output=typed_output.structured_output,
                artifacts=typed_output.artifacts,
                diagnostics=diagnostics,
                runtime_input_metadata=prepared.step_input.runtime_input_metadata,
            )
        )
