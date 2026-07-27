from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from eneo.flows.domain.flow import FlowRun
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepInputValue
from eneo.flows.enums import FlowOutputMode
from eneo.flows.runtime.step_execution_result import StepExecutionResult
from eneo.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
)


@dataclass(frozen=True)
class PreparedAssistantStep:
    prepared: PreparedStepExecution
    deps: StepExecutionRuntimeDeps


ActivatePreparedAssistantStepsFn = Callable[
    [
        FlowRun,
        RuntimeStep,
        RunExecutionState,
        int,
        Sequence[PreparedAssistantStep],
    ],
    Awaitable[tuple[PreparedAssistantStep, ...]],
]


class PrepareAssistantStepFn(Protocol):
    async def __call__(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
        requested_file_ids_override: Sequence[UUID] | None = None,
        step_input_override: StepInputValue | None = None,
    ) -> PreparedAssistantStep: ...


class PreviewAssistantStepFn(Protocol):
    async def __call__(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        state: RunExecutionState,
        version_metadata: dict[str, object] | None,
        attempt_no: int,
        requested_file_ids_override: Sequence[UUID] | None = None,
        step_input_override: StepInputValue | None = None,
    ) -> PreparedAssistantStep: ...


class ListStepInputFileIdsFn(Protocol):
    async def __call__(
        self,
        *,
        step: RuntimeStep,
        run: FlowRun,
        attempt_no: int,
    ) -> list[UUID]: ...


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
        attempt_no: int,
    ) -> StepExecutionResult: ...
