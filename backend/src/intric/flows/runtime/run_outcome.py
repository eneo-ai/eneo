from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from intric.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationResult,
    FlowRunTerminalizer,
)
from intric.flows.domain.flow import (
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.enums import FlowRunLifecycleSource
from intric.flows.flow_run_error import FlowRunError
from intric.flows.principal import FlowPrincipal


@dataclass(frozen=True)
class RunOutcome:
    result_status: str
    flow_status: str | None = None
    error_message: str | None = None
    output_payload_json: dict[str, Any] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RunFinalizationResult:
    payload: dict[str, str]
    terminalization: FlowRunTerminalizationResult | None


def determine_run_outcome(*, results: list[FlowStepResult]) -> RunOutcome:
    if any(item.status == FlowStepResultStatus.FAILED for item in results):
        return RunOutcome(
            result_status="failed",
            flow_status="failed",
            error_message="One or more flow steps failed.",
        )

    if any(
        item.status in (FlowStepResultStatus.PENDING, FlowStepResultStatus.RUNNING)
        for item in results
    ):
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
            for item in sorted(
                results, key=lambda result: result.step_order, reverse=True
            )
            if item.status == FlowStepResultStatus.COMPLETED
        ),
        None,
    )
    return RunOutcome(
        result_status="completed",
        flow_status="completed",
        output_payload_json=last_completed.output_payload_json
        if last_completed
        else None,
    )


async def finalize_run_from_current_results(
    *,
    run_id: UUID,
    tenant_id: UUID,
    results: list[FlowStepResult],
    terminalizer: FlowRunTerminalizer,
    principal: FlowPrincipal | None = None,
) -> RunFinalizationResult:
    outcome = determine_run_outcome(results=results)
    if outcome.result_status == "skipped":
        return RunFinalizationResult(
            payload={
                "status": "skipped",
                "reason": outcome.reason or "run_in_progress",
            },
            terminalization=None,
        )

    if outcome.flow_status is None:
        raise RuntimeError("Terminal run outcome must include flow_status.")

    target_status = FlowRunStatus(outcome.flow_status)
    failure_source = FlowRunLifecycleSource.EXECUTOR_FAILED
    run_error = (
        FlowRunError.from_source(
            failure_source,
            code=outcome.reason or failure_source.value,
            message=(
                outcome.error_message
                or outcome.reason
                or "One or more flow steps failed."
            ),
        )
        if target_status != FlowRunStatus.COMPLETED
        else None
    )
    source = (
        FlowRunLifecycleSource.EXECUTOR_COMPLETED
        if target_status == FlowRunStatus.COMPLETED
        else failure_source
    )
    terminalization = await terminalizer.terminalize_run(
        run_id=run_id,
        tenant_id=tenant_id,
        target_status=target_status,
        source=source,
        error=run_error,
        output_payload_json=outcome.output_payload_json,
        principal=principal,
    )
    return RunFinalizationResult(
        payload={"status": terminalization.run.status.value},
        terminalization=terminalization,
    )
