from __future__ import annotations

from dataclasses import dataclass

from intric.flows.domain.flow import FlowRun
from intric.flows.enums import FlowOutputMode
from intric.flows.runtime.models import RunExecutionState, RuntimeStep
from intric.flows.runtime.step_execution_result import StepExecutionResult
from intric.flows.runtime.step_execution_runtime import complete_step_execution
from intric.flows.runtime.step_handlers.base import PrepareAssistantStepFn


@dataclass(frozen=True)
class PassThroughStepHandler:
    prepare_assistant_step: PrepareAssistantStepFn
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
