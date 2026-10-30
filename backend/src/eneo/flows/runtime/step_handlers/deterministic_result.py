"""The final result of deterministic text, document and JSON handlers."""

from __future__ import annotations

from uuid import UUID

from eneo.flows.domain.runtime import StepDiagnostic, StepExecutionOutput
from eneo.flows.enums import FlowOutputMode
from eneo.flows.runtime.output_runtime import TypedOutputProcessingResult
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import PreparedStepExecution


def deterministic_result(
    *,
    prepared: PreparedStepExecution,
    typed_output: TypedOutputProcessingResult,
    output_text: str,
    persisted_text: str,
    generated_file_ids: list[UUID],
    mode: FlowOutputMode,
    diagnostic: StepDiagnostic,
) -> StepExecutionResult:
    """Construct the result after each handler's own validation and byte cap."""
    return StepExecutionResult(
        output=StepExecutionOutput(
            input_text=prepared.step_input.text,
            source_text=prepared.step_input.source_text,
            input_source=prepared.step_input.input_source,
            used_question_binding=prepared.step_input.used_question_binding,
            full_text=output_text,
            persisted_text=persisted_text,
            generated_file_ids=generated_file_ids,
            tool_calls_metadata=None,
            num_tokens_input=0,
            num_tokens_output=0,
            effective_prompt="",
            model_parameters_json={"mode": mode.value},
            contract_validation=prepared.contract_validation,
            structured_output=typed_output.structured_output,
            artifacts=typed_output.artifacts,
            diagnostics=[*prepared.diagnostics, *typed_output.diagnostics, diagnostic],
            runtime_input_metadata=prepared.step_input.runtime_input_metadata,
        )
    )
