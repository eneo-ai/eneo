from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intric.flows.flow import FlowStepResult, FlowStepResultStatus


@dataclass(frozen=True)
class RunOutcome:
    result_status: str
    flow_status: str | None = None
    error_message: str | None = None
    output_payload_json: dict[str, Any] | None = None
    reason: str | None = None


def determine_run_outcome(*, results: list[FlowStepResult]) -> RunOutcome:
    if any(item.status == FlowStepResultStatus.FAILED for item in results):
        return RunOutcome(
            result_status="failed",
            flow_status="failed",
            error_message="One or more flow steps failed.",
        )

    if any(item.status in (FlowStepResultStatus.PENDING, FlowStepResultStatus.RUNNING) for item in results):
        return RunOutcome(
            result_status="skipped",
            reason="run_in_progress",
        )

    if any(item.status == FlowStepResultStatus.CANCELLED for item in results):
        return RunOutcome(
            result_status="cancelled",
            flow_status="cancelled",
            error_message="One or more steps were cancelled.",
        )

    last_completed = next(
        (
            item
            for item in sorted(results, key=lambda result: result.step_order, reverse=True)
            if item.status == FlowStepResultStatus.COMPLETED
        ),
        None,
    )
    return RunOutcome(
        result_status="completed",
        flow_status="completed",
        output_payload_json=last_completed.output_payload_json if last_completed else None,
    )
