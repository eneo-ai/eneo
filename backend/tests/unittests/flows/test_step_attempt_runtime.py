from __future__ import annotations

from datetime import datetime, timezone
from typing import get_type_hints
from uuid import uuid4

from eneo.flows.domain.flow import (
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
    FlowAttemptProvenance,
    parse_attempt_provenance,
)
from eneo.flows.runtime.claim_resolution import StepClaimResolution
from eneo.flows.runtime.executor import _build_attempt_provenance
from eneo.flows.runtime.models import RuntimeStep, StepDiagnostic, StepExecutionOutput
from eneo.flows.runtime.step_attempt_runtime import (
    StepFailurePlan,
    build_generic_failure_plan,
    build_step_gate_decision,
    build_step_success_plan,
    build_typed_failure_plan,
    build_typed_failure_run_error_message,
)
from eneo.flows.runtime.step_execution_result import (
    StepExecutionResult,
    WebhookDeliveryIntent,
    WebhookPayloadRef,
)
from eneo.flows.runtime.step_result_builder import build_completed_step_result


def _claimed_result(*, step_order: int = 1) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json={"text": "input"},
        effective_prompt="prompt",
        output_payload_json={"text": "output"},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.RUNNING,
        error_message=None,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


def _runtime_step(
    *, input_source: str = "flow_input", output_mode: str = "pass_through"
) -> RuntimeStep:
    claimed = _claimed_result()
    return RuntimeStep(
        step_id=claimed.step_id,
        step_order=claimed.step_order,
        assistant_id=claimed.assistant_id,
        user_description=None,
        input_source=input_source,
        input_bindings=None,
        input_config=None,
        output_mode=output_mode,
        output_config=None,
        output_type="text",
        input_type="text",
    )


def _step_output() -> StepExecutionOutput:
    return StepExecutionOutput(
        input_text="hello",
        source_text="hello",
        input_source="flow_input",
        used_question_binding=False,
        full_text="done",
        persisted_text="done",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=2,
        num_tokens_output=3,
        effective_prompt="prompt",
        model_parameters_json={"temperature": 0.2},
    )


def test_build_step_gate_decision_returns_cancel_plan_for_deleted_flow():
    decision = build_step_gate_decision(
        latest_run_status=FlowRunStatus.RUNNING,
        flow_active=False,
        claim_resolution=None,
        step_id=uuid4(),
    )

    assert decision.action == "cancel_flow_deleted"
    assert decision.result == {"status": "cancelled", "reason": "flow_deleted"}
    assert decision.run_error_message == "Flow was deleted during execution."


def test_build_step_gate_decision_returns_skip_for_terminal_run():
    decision = build_step_gate_decision(
        latest_run_status=FlowRunStatus.CANCELLED,
        flow_active=True,
        claim_resolution=None,
        step_id=uuid4(),
    )

    assert decision.action == "return"
    assert decision.result == {"status": "skipped", "reason": "run_cancelled"}


def test_build_step_gate_decision_returns_failure_for_missing_step_result():
    step_id = uuid4()
    decision = build_step_gate_decision(
        latest_run_status=FlowRunStatus.RUNNING,
        flow_active=True,
        claim_resolution=StepClaimResolution(action="missing_step_result"),
        step_id=step_id,
    )

    assert decision.action == "fail_step_missing"
    assert decision.result == {
        "status": "failed",
        "error": FlowApiErrorCode.STEP_MISSING.value,
    }
    assert decision.run_error_message == f"Missing step result for step {step_id}"


def test_build_step_gate_decision_appends_completed_result():
    existing = _claimed_result()
    decision = build_step_gate_decision(
        latest_run_status=FlowRunStatus.RUNNING,
        flow_active=True,
        claim_resolution=StepClaimResolution(
            action="append_completed", completed_result=existing
        ),
        step_id=existing.step_id,
    )

    assert decision.action == "append_completed"
    assert decision.completed_result == existing


def test_build_step_gate_decision_uses_continue_for_skip_resolution():
    decision = build_step_gate_decision(
        latest_run_status=FlowRunStatus.RUNNING,
        flow_active=True,
        claim_resolution=StepClaimResolution(action="skip"),
        step_id=uuid4(),
    )

    assert decision.action == "continue"


def test_build_typed_failure_plan_preserves_input_payload_and_prompt():
    claimed = _claimed_result()
    plan = build_typed_failure_plan(
        claimed=claimed,
        error_code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION,
        error_message="Step 1 input invalid",
        input_payload_json={"text": "bad", "input_source": "flow_input"},
        effective_prompt="Prompt",
    )

    assert plan.attempt_status == FlowStepAttemptStatus.FAILED
    assert plan.error_code is FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION
    assert plan.failed_result.status == FlowStepResultStatus.FAILED
    assert plan.failed_result.error_code == "typed_io_contract_violation"
    assert plan.failed_result.input_payload_json == {
        "text": "bad",
        "input_source": "flow_input",
    }
    assert plan.failed_result.effective_prompt == "Prompt"
    assert plan.return_result == {"status": "failed", "error": "Step 1 input invalid"}


def test_step_failure_plan_error_code_is_typed_to_public_catalog():
    hints = get_type_hints(StepFailurePlan)

    assert hints["error_code"] is FlowApiErrorCode


def test_typed_failure_run_error_uses_public_taxonomy_summary() -> None:
    message = build_typed_failure_run_error_message(
        step_order=1,
        error_code=FlowApiErrorCode.TYPED_IO_TRANSCRIPTION_FAILED,
        error_message="provider secret must remain private",
        contract_validation=None,
    )

    assert message == (
        "Step 1: The transcription provider failed while processing audio "
        "(typed_io_transcription_failed)."
    )
    assert ". (" not in message


def test_typed_failure_run_error_preserves_contract_validation_summary() -> None:
    message = build_typed_failure_run_error_message(
        step_order=2,
        error_code=FlowApiErrorCode.TYPED_IO_OUTPUT_PARSE_FAILED,
        error_message="raw parse detail",
        contract_validation={
            "parse_attempted": True,
            "parse_succeeded": False,
            "schema_type_hint": "object",
        },
    )

    assert message == (
        "Step 2: expected valid JSON text for structured object input "
        "(typed_io_output_parse_failed)."
    )


def test_variable_resolution_run_error_preserves_precise_resolver_message() -> None:
    resolver_message = (
        "Unknown variable reference: 'flow.input.question'. "
        "Missing key 'question'. Available keys: case_id."
    )

    message = build_typed_failure_run_error_message(
        step_order=3,
        error_code=FlowApiErrorCode.TYPED_IO_VARIABLE_RESOLUTION_FAILED,
        error_message=resolver_message,
        contract_validation=None,
    )

    assert message == (
        f"Step 3: {resolver_message} (typed_io_variable_resolution_failed)."
    )


def test_typed_failure_plan_keeps_raw_detail_out_of_run_error() -> None:
    claimed = _claimed_result()
    raw_detail = (
        "Step 1: HTTP GET input request failed for "
        "https://internal.example.test/token=secret."
    )
    run_error_message = build_typed_failure_run_error_message(
        step_order=1,
        error_code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR,
        error_message=raw_detail,
        contract_validation=None,
    )

    plan = build_typed_failure_plan(
        claimed=claimed,
        error_code=FlowApiErrorCode.TYPED_IO_HTTP_CONNECTION_ERROR,
        error_message=raw_detail,
        run_error_message=run_error_message,
    )

    assert plan.failed_result.error_message == raw_detail
    assert plan.run_error_message == (
        "Step 1: The HTTP step could not connect to the target service "
        "(typed_io_http_connection_error)."
    )
    assert "secret" not in plan.run_error_message
    assert "internal.example.test" not in plan.run_error_message


def test_build_generic_failure_plan_uses_public_error_contract():
    claimed = _claimed_result()

    plan = build_generic_failure_plan(
        claimed=claimed,
        public_error="Flow step 1 execution failed.",
    )

    assert plan.attempt_status == FlowStepAttemptStatus.FAILED
    assert plan.error_code is FlowApiErrorCode.STEP_EXECUTION_FAILED
    assert plan.error_message == "Flow step 1 execution failed."
    assert plan.failed_result.error_code == FlowApiErrorCode.STEP_EXECUTION_FAILED.value
    assert plan.failed_result.error_message == "Flow step 1 execution failed."
    assert plan.return_result == {
        "status": "failed",
        "error": FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
    }


def test_build_step_success_plan_follows_delivery_intents_not_output_mode():
    claimed = _claimed_result()
    step = _runtime_step(output_mode="http_post")
    output = _step_output()

    plan = build_step_success_plan(
        claimed=claimed,
        run_id=claimed.flow_run_id,
        flow_id=claimed.flow_id,
        tenant_id=claimed.tenant_id,
        step=step,
        result=StepExecutionResult(output=output),
        output_payload_json={
            "text": "done",
        },
        execution_hash="exec-hash",
    )

    assert plan.delivery_intents == ()
    assert plan.step_result.status == FlowStepResultStatus.COMPLETED
    assert plan.step_result.error_code is None
    assert plan.step_result.output_payload_json == {
        "text": "done",
    }

    claimed_without_http_mode = _claimed_result()
    step = _runtime_step(output_mode="pass_through")
    intent = WebhookDeliveryIntent(
        flow_run_id=claimed_without_http_mode.flow_run_id,
        step_id=step.step_id,
        step_order=step.step_order,
        attempt_no=2,
        idempotency_key=(
            f"{claimed_without_http_mode.flow_run_id}:{step.step_id}:2:webhook"
        ),
        payload=WebhookPayloadRef(
            value=(
                f"flow_run:{claimed_without_http_mode.flow_run_id}:"
                f"step:{step.step_id}:attempt:2"
            )
        ),
    )

    plan = build_step_success_plan(
        claimed=claimed_without_http_mode,
        run_id=claimed_without_http_mode.flow_run_id,
        flow_id=claimed_without_http_mode.flow_id,
        tenant_id=claimed_without_http_mode.tenant_id,
        step=step,
        result=StepExecutionResult(
            output=_step_output(),
            delivery_intents=(intent,),
        ),
        output_payload_json={
            "text": "done",
        },
        execution_hash="exec-hash",
    )

    assert plan.delivery_intents == (intent,)


def test_build_attempt_provenance_round_trips_all_runtime_sections() -> None:
    claimed = _claimed_result()
    generated_file_id = uuid4()
    step = _runtime_step(input_source="http_get", output_mode="http_post")
    output = _step_output()
    output.generated_file_ids = [generated_file_id]
    output.artifacts = [
        {
            "file_id": str(generated_file_id),
            "file_name": "answer.docx",
        }
    ]
    output.tool_calls_metadata = [{"name": "lookup", "arguments": {"q": "case"}}]
    output.raw_completion_text = "raw completion"
    output.rag_metadata = {"status": "success"}
    output.runtime_input_metadata = {"files_count": 1}
    output.transcription_metadata = {"segments": [{"index": 1, "text": "hello"}]}
    output.contract_validation = {"valid": True}
    output.diagnostics = [
        StepDiagnostic(
            code="contract_warning",
            message="Contract warning",
            severity="warning",
        )
    ]
    output.citation_sidecar = {"tracking_mode": "passive_inline_scan"}
    step_result = claimed.model_copy(
        update={
            "output_payload_json": {
                "template_provenance": {"template_id": "template-1"},
            }
        }
    )

    provenance_payload = _build_attempt_provenance(
        step=step,
        output=output,
        step_result=step_result,
    )

    validated = FlowAttemptProvenance.model_validate(provenance_payload)
    assert provenance_payload == validated.to_payload()
    assert parse_attempt_provenance(provenance_payload).status == "tracked"
    assert provenance_payload["schema_version"] == (
        FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION
    )
    assert set(provenance_payload) == {
        "schema_version",
        "llm",
        "rag",
        "runtime_input",
        "transcription",
        "guards",
        "template",
        "artifacts",
        "http",
        "citations",
    }
    assert provenance_payload["http"] == {
        "input_source": "http_get",
        "structured_input_present": True,
        "output_mode": "http_post",
    }
    assert set(provenance_payload["llm"]) <= {
        "effective_prompt",
        "model_parameters",
        "tool_calls",
        "raw_completion_text",
    }
    assert provenance_payload["artifacts"]["generated_file_ids"] == [
        str(generated_file_id)
    ]


def test_runtime_tool_calls_land_in_attempt_provenance_not_step_result() -> None:
    claimed = _claimed_result()
    step = _runtime_step()
    output = _step_output()
    output.tool_calls_metadata = [{"name": "lookup", "arguments": {"q": "case"}}]

    step_result = build_completed_step_result(
        claimed=claimed,
        run_id=claimed.flow_run_id,
        flow_id=claimed.flow_id,
        tenant_id=claimed.tenant_id,
        step=step,
        output=output,
        output_payload_json={"text": "done"},
        execution_hash="exec-hash",
    )
    provenance_payload = _build_attempt_provenance(
        step=step,
        output=output,
        step_result=step_result,
    )

    parse_result = parse_attempt_provenance(provenance_payload)
    assert parse_result.provenance is not None
    assert parse_result.provenance.llm is not None
    assert parse_result.provenance.llm.tool_calls is not None
    assert provenance_payload["llm"]["tool_calls"]["preview"] == [
        {"name": "lookup", "arguments": {"q": "case"}}
    ]
