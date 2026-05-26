from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from intric.flows.domain.flow import FlowRun
from intric.flows.enums import FlowOutputMode
from intric.flows.runtime.models import RunExecutionState, RuntimeStep
from intric.flows.runtime.step_execution_result import StepExecutionResult
from intric.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
)


@dataclass(frozen=True)
class PreparedAssistantStep:
    prepared: PreparedStepExecution
    deps: StepExecutionRuntimeDeps


class PrepareAssistantStepFn(Protocol):
    async def __call__(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int | None,
    ) -> PreparedAssistantStep: ...


class StepHandler(Protocol):
    @property
    def output_mode(self) -> FlowOutputMode: ...

    async def execute(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int | None,
    ) -> StepExecutionResult: ...
