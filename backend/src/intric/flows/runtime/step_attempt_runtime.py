from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from intric.flows.domain.flow import (
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
)
from intric.flows.enums import is_terminal_flow_run_status
from intric.flows.runtime.claim_resolution import StepClaimResolution
from intric.flows.runtime.models import RuntimeStep
from intric.flows.runtime.step_execution_result import StepExecutionResult
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
    if is_terminal_flow_run_status(latest_run_status):
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
    run_error_message: str | None = None,
) -> StepFailurePlan:
    public_error = run_error_message or error_message
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
        run_error_message=public_error,
        return_result={"status": "failed", "error": public_error},
    )


def build_typed_failure_run_error_message(
    *,
    step_order: int,
    error_code: str,
    contract_validation: object | None,
) -> str:
    summary = _contract_validation_summary(contract_validation)
    if summary is not None:
        return f"Step {step_order}: {summary} ({error_code})."
    return f"Step {step_order}: typed input/output validation failed ({error_code})."


def _contract_validation_summary(contract_validation: object | None) -> str | None:
    if not isinstance(contract_validation, Mapping):
        return None
    validation = cast(Mapping[object, object], contract_validation)
    parse_attempted = validation.get("parse_attempted") is True
    parse_succeeded = validation.get("parse_succeeded") is True
    if not parse_attempted or parse_succeeded:
        return None
    schema_type_hint = validation.get("schema_type_hint")
    if schema_type_hint in {"object", "array"}:
        return f"expected valid JSON text for structured {schema_type_hint} input"
    return "expected valid JSON text for structured input"


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
    result: StepExecutionResult,
    output_payload_json: dict[str, Any],
    execution_hash: str,
) -> StepSuccessPlan:
    output = result.output
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
        should_deliver_webhook=bool(result.delivery_intents),
    )
