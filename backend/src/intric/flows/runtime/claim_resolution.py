from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.runtime.models import RunExecutionState


ClaimAction = Literal["proceed", "missing_step_result", "step_already_claimed", "append_completed", "skip"]


@dataclass(frozen=True)
class StepClaimResolution:
    action: ClaimAction
    error: str | None = None
    completed_result: FlowStepResult | None = None
    reason: str | None = None


def resolve_step_claim(
    *,
    claimed: FlowStepResult | None,
    existing: FlowStepResult | None,
    state: RunExecutionState,
) -> StepClaimResolution:
    if claimed is not None:
        return StepClaimResolution(action="proceed")

    if existing is None:
        return StepClaimResolution(
            action="missing_step_result",
            error="Missing claimed step result.",
        )

    if existing.status in (
        FlowStepResultStatus.PENDING,
        FlowStepResultStatus.RUNNING,
    ):
        return StepClaimResolution(
            action="step_already_claimed",
            reason="step_already_claimed",
        )

    if (
        existing.status == FlowStepResultStatus.COMPLETED
        and existing.step_order not in state.completed_by_order
    ):
        return StepClaimResolution(
            action="append_completed",
            completed_result=existing,
        )

    return StepClaimResolution(action="skip")
