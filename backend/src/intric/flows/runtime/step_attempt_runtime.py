from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from intric.flows.flow import FlowRunStatus, FlowStepAttemptStatus, FlowStepResult
from intric.flows.runtime.claim_resolution import StepClaimResolution
from intric.flows.runtime.models import RuntimeStep, StepExecutionOutput
from intric.flows.runtime.step_result_builder import (
    build_completed_step_result,
    build_failed_step_result,
)


StepGateAction = Literal[
    "execute_attempt",
    "return",
    "cancel_flow_deleted",
    "fail_step_missing",
    "append_completed",
    "continue",
]


@dataclass(frozen=True)
class StepGateDecision:
    action: StepGateAction
    result: dict[str, Any] | None = None
    run_error_message: str | None = None
    completed_result: FlowStepResult | None = None


@dataclass(frozen=True)
class StepFailurePlan:
    attempt_status: FlowStepAttemptStatus
    error_code: str
    error_message: str
    failed_result: FlowStepResult
    run_error_message: str
    return_result: dict[str, Any]


@dataclass(frozen=True)
class StepSuccessPlan:
    step_result: FlowStepResult
    should_deliver_webhook: bool


def build_step_gate_decision(
    *,
    latest_run_status: FlowRunStatus,
    flow_active: bool,
    claim_resolution: StepClaimResolution | None,
    step_id: UUID,
) -> StepGateDecision:
    if latest_run_status in {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }:
        return StepGateDecision(
            action="return",
            result={"status": "skipped", "reason": f"run_{latest_run_status.value}"},
        )

    if not flow_active:
        return StepGateDecision(
            action="cancel_flow_deleted",
            result={"status": "cancelled", "reason": "flow_deleted"},
            run_error_message="Flow was deleted during execution.",
        )

    if claim_resolution is None or claim_resolution.action == "proceed":
        return StepGateDecision(action="execute_attempt")

    if claim_resolution.action == "missing_step_result":
        return StepGateDecision(
            action="fail_step_missing",
            result={"status": "failed", "error": "step_missing"},
            run_error_message=f"Missing step result for step {step_id}",
        )

    if claim_resolution.action == "step_already_claimed":
        return StepGateDecision(
            action="return",
            result={"status": "skipped", "reason": "step_already_claimed"},
        )

    if claim_resolution.action == "append_completed":
        return StepGateDecision(
            action="append_completed",
            completed_result=claim_resolution.completed_result,
        )

    return StepGateDecision(action="continue")


def build_typed_failure_plan(
    *,
    claimed: FlowStepResult,
    error_code: str,
    error_message: str,
    input_payload_json: dict[str, Any] | None = None,
    effective_prompt: str | None = None,
) -> StepFailurePlan:
    return StepFailurePlan(
        attempt_status=FlowStepAttemptStatus.FAILED,
        error_code=error_code,
        error_message=error_message,
        failed_result=build_failed_step_result(
            claimed=claimed,
            error_message=error_message,
            input_payload_json=input_payload_json,
            effective_prompt=effective_prompt,
        ),
        run_error_message=error_message,
        return_result={"status": "failed", "error": error_message},
    )


def build_generic_failure_plan(
    *,
    claimed: FlowStepResult,
    public_error: str,
) -> StepFailurePlan:
    return StepFailurePlan(
        attempt_status=FlowStepAttemptStatus.FAILED,
        error_code="step_execution_failed",
        error_message=public_error,
        failed_result=build_failed_step_result(
            claimed=claimed,
            error_message=public_error,
        ),
        run_error_message=public_error,
        return_result={"status": "failed", "error": "step_execution_failed"},
    )


def build_step_success_plan(
    *,
    claimed: FlowStepResult,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    step: RuntimeStep,
    output: StepExecutionOutput,
    output_payload_json: dict[str, Any],
    execution_hash: str,
) -> StepSuccessPlan:
    return StepSuccessPlan(
        step_result=build_completed_step_result(
            claimed=claimed,
            run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step=step,
            output=output,
            output_payload_json=output_payload_json,
            execution_hash=execution_hash,
        ),
        should_deliver_webhook=step.output_mode == "http_post",
    )
