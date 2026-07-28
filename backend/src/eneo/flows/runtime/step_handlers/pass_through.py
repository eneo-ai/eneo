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
from eneo.flows.runtime.step_handlers.per_item_map import (
    execute_per_item_map,
    should_execute_per_item_map,
)
from eneo.flows.runtime.step_handlers.per_source_reader import (
    execute_per_source_reader,
    should_execute_per_source_reader,
)
from eneo.flows.runtime_input import build_runtime_input_config
from eneo.flows.step_item_map import build_step_item_map_config
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
        if should_execute_per_source_reader(step):
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
        if should_execute_per_item_map(step):
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
        runtime_input = build_runtime_input_config(step.input_config)
        if runtime_input.execution_mode == "per_source":
            raise TypedIOValidationException(
                "Per-source execution is configured but the step is not a "
                "supported per-source document reader.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        item_map = build_step_item_map_config(step.input_config)
        if item_map.enabled:
            raise TypedIOValidationException(
                "Per-item map execution is configured but the step is not a "
                "supported previous-step JSON map.",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
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
