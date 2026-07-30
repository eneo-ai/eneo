from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    resolve_flow_mapped_execution_policy,
)
from eneo.flows.domain.rag_evidence_policy import FlowRagEvidencePolicy
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import complete_step_execution
from eneo.flows.runtime.step_handlers.base import (
    ActivatePreparedAssistantStepsFn,
    ListStepInputFileIdsFn,
    PrepareAssistantStepFn,
    PreviewAssistantStepFn,
)
from eneo.flows.runtime.step_handlers.per_item_map import execute_per_item_map
from eneo.flows.runtime.step_handlers.per_source_reader import (
    execute_per_source_reader,
)
from eneo.flows.step_mapped_execution import (
    FlowStepMappedExecutionConfigurationError,
    resolve_step_mapped_execution,
)
from eneo.main.exceptions import TypedIOValidationException


@dataclass(frozen=True)
class PassThroughStepHandler:
    prepare_assistant_step: PrepareAssistantStepFn
    preview_assistant_step: PreviewAssistantStepFn | None = None
    list_step_input_file_ids: ListStepInputFileIdsFn | None = None
    activate_prepared_assistant_steps: ActivatePreparedAssistantStepsFn | None = None
    mapped_execution_policy: FlowMappedExecutionPolicy = (
        resolve_flow_mapped_execution_policy(None)
    )
    rag_evidence_policy: FlowRagEvidencePolicy = FlowRagEvidencePolicy()
    output_mode: FlowOutputMode = FlowOutputMode.PASS_THROUGH

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
    ) -> StepExecutionResult:
        try:
            mapped_execution = resolve_step_mapped_execution(
                input_source=step.input_source,
                input_type=step.input_type,
                output_mode=step.output_mode,
                output_type=step.output_type,
                input_config=step.input_config,
            )
        except FlowStepMappedExecutionConfigurationError as exc:
            raise TypedIOValidationException(
                str(exc),
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            ) from exc

        if (
            mapped_execution is not None
            and mapped_execution.execution_mode == "per_source"
        ):
            if self.list_step_input_file_ids is None:
                raise RuntimeError(
                    "Per-source reader execution requires file-id listing."
                )
            if self.preview_assistant_step is None:
                raise RuntimeError(
                    "Per-source reader execution requires side-effect-free preview."
                )
            if self.activate_prepared_assistant_steps is None:
                raise RuntimeError(
                    "Per-source reader execution requires attempt activation."
                )
            return await execute_per_source_reader(
                step=step,
                run=run,
                state=state,
                version_metadata=version_metadata,
                attempt_no=attempt_no,
                preview_assistant_step=self.preview_assistant_step,
                activate_prepared_assistant_steps=(
                    self.activate_prepared_assistant_steps
                ),
                list_step_input_file_ids=self.list_step_input_file_ids,
                mapped_execution_policy=self.mapped_execution_policy,
                rag_evidence_policy=self.rag_evidence_policy,
            )
        if (
            mapped_execution is not None
            and mapped_execution.execution_mode == "per_item"
        ):
            if self.preview_assistant_step is None:
                raise RuntimeError(
                    "Per-item map execution requires side-effect-free preview."
                )
            if self.activate_prepared_assistant_steps is None:
                raise RuntimeError(
                    "Per-item map execution requires attempt activation."
                )
            return await execute_per_item_map(
                step=step,
                run=run,
                state=state,
                version_metadata=version_metadata,
                attempt_no=attempt_no,
                preview_assistant_step=self.preview_assistant_step,
                activate_prepared_assistant_steps=(
                    self.activate_prepared_assistant_steps
                ),
                mapped_execution_policy=self.mapped_execution_policy,
                rag_evidence_policy=self.rag_evidence_policy,
            )
        prepared_step = await self.prepare_assistant_step(
            step=step,
            run=run,
            state=state,
            version_metadata=version_metadata,
            attempt_no=attempt_no,
        )
        output = await complete_step_execution(
            step=step,
            run=run,
            state=state,
            prepared=prepared_step.prepared,
            deps=prepared_step.deps,
        )
        return StepExecutionResult(output=output)
