from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_run_provenance import FlowResolvedInputEdge
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.template_fill_runtime import (
    TemplateFillRuntimeDeps,
    complete_template_fill_step,
    prepare_template_fill_step,
)

ActivateResolvedInputEdges = Callable[
    [
        FlowRun,
        RuntimeStep,
        RunExecutionState,
        int,
        tuple[FlowResolvedInputEdge, ...],
    ],
    Awaitable[None],
]


@dataclass(frozen=True)
class TemplateFillStepHandler:
    deps: TemplateFillRuntimeDeps
    activate_resolved_input_edges: ActivateResolvedInputEdges
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
        prepared = await prepare_template_fill_step(
            step=step,
            run=run,
            state=state,
            deps=self.deps,
        )
        await self.activate_resolved_input_edges(
            run,
            step,
            state,
            attempt_no,
            prepared.resolved_input_edges,
        )
        output = await complete_template_fill_step(
            step=step,
            run=run,
            prepared=prepared,
            deps=self.deps,
        )
        return StepExecutionResult(output=output)
