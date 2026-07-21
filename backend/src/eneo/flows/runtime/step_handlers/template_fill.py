from __future__ import annotations

from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.enums import FlowOutputMode
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.template_fill_runtime import (
    TemplateFillRuntimeDeps,
    execute_template_fill_step,
)


@dataclass(frozen=True)
class TemplateFillStepHandler:
    deps: TemplateFillRuntimeDeps
    output_mode: FlowOutputMode = FlowOutputMode.TEMPLATE_FILL

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
    ) -> StepExecutionResult:
        output = await execute_template_fill_step(
            step=step,
            run=run,
            state=state,
            deps=self.deps,
        )
        return StepExecutionResult(output=output)
