from __future__ import annotations

from dataclasses import dataclass

from pydantic import ConfigDict, TypeAdapter, ValidationError

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepDiagnostic
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.output_modes import copy_input_violation
from eneo.flows.output_processing import StructuredOutputValue
from eneo.flows.runtime.contract_check import check_contract_in_child
from eneo.flows.runtime.output_runtime import TypedOutputProcessingResult
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import attach_typed_failure_context
from eneo.flows.runtime.step_handlers.base import PrepareAssistantStepFn
from eneo.flows.runtime.step_handlers.deterministic_result import deterministic_result
from eneo.flows.runtime.structured_output_budget import (
    ensure_structured_output_allowed,
    structured_output_json,
)
from eneo.main.exceptions import TypedIOValidationException

_JSON_CONTAINER = TypeAdapter[StructuredOutputValue](
    StructuredOutputValue, config=ConfigDict(allow_inf_nan=False)
)


@dataclass(frozen=True)
class CopyInputStepHandler:
    prepare_assistant_step: PrepareAssistantStepFn
    output_mode: FlowOutputMode = FlowOutputMode.COPY_INPUT

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
        prepared, deps = prepared_step.prepared, prepared_step.deps
        try:
            mode_error = copy_input_violation(
                step_order=step.step_order,
                input_type=step.input_type,
                output_type=step.output_type,
                output_mode=step.output_mode,
            )
            if mode_error is not None:
                raise TypedIOValidationException(
                    mode_error,
                    code=FlowApiErrorCode.TYPED_IO_INVALID_OUTPUT_MODE_COMBINATION.value,
                )
            try:
                # This boundary accepts only an existing JSON container. Strict
                # validation preserves values and names; model-output repair is
                # deliberately not part of a deterministic copy.
                structured = _JSON_CONTAINER.validate_python(
                    prepared.step_input.structured, strict=True
                )
            except ValidationError as exc:
                raise TypedIOValidationException(
                    f"Step {step.step_order}: copy_input requires a resolved JSON object or array.",
                    code=FlowApiErrorCode.TYPED_IO_INVALID_JSON_INPUT.value,
                ) from exc
            ensure_structured_output_allowed(
                structured, ceiling_bytes=deps.max_inline_text_bytes
            )
            if step.output_contract is not None:
                await check_contract_in_child(
                    structured,
                    step.output_contract,
                    label=f"Step {step.step_order} output",
                    side="output",
                )
            output_text = structured_output_json(structured)
            persisted_text, generated_file_ids = await deps.apply_output_cap(
                text=output_text,
                run=run,
                step=step,
            )
        except TypedIOValidationException as exc:
            raise attach_typed_failure_context(
                exc,
                input_payload_for_result=prepared.input_payload_for_result,
                effective_prompt="",
            ) from exc
        return deterministic_result(
            prepared=prepared,
            typed_output=TypedOutputProcessingResult(
                structured_output=structured, artifacts=None, diagnostics=[]
            ),
            output_text=output_text,
            persisted_text=persisted_text,
            generated_file_ids=generated_file_ids,
            mode=self.output_mode,
            diagnostic=StepDiagnostic(
                code="copy_input_used",
                severity="info",
                message=f"Step {step.step_order}: copy_input preserved resolved JSON without calling the assistant.",
            ),
        )
