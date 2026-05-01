from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from intric.flows.flow import (
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.flow_run_provenance import (
    FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
    FlowAttemptProvenance,
    parse_attempt_provenance,
)
from intric.flows.runtime.claim_resolution import StepClaimResolution
from intric.flows.runtime.executor import _build_attempt_provenance
from intric.flows.runtime.models import RuntimeStep, StepDiagnostic, StepExecutionOutput
from intric.flows.runtime.step_attempt_runtime import (
    build_generic_failure_plan,
    build_step_gate_decision,
    build_step_success_plan,
    build_typed_failure_plan,
)


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
        tool_calls_metadata=None,
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
        legacy_prompt_binding_used=False,
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
    assert decision.result == {"status": "failed", "error": "step_missing"}
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
        error_code="typed_io_contract_violation",
        error_message="Step 1 input invalid",
        input_payload_json={"text": "bad", "input_source": "flow_input"},
        effective_prompt="Prompt",
    )

    assert plan.attempt_status == FlowStepAttemptStatus.FAILED
    assert plan.error_code == "typed_io_contract_violation"
    assert plan.failed_result.status == FlowStepResultStatus.FAILED
    assert plan.failed_result.input_payload_json == {
        "text": "bad",
        "input_source": "flow_input",
    }
    assert plan.failed_result.effective_prompt == "Prompt"
    assert plan.return_result == {"status": "failed", "error": "Step 1 input invalid"}


def test_build_generic_failure_plan_uses_public_error_contract():
    claimed = _claimed_result()

    plan = build_generic_failure_plan(
        claimed=claimed,
        public_error="Flow step 1 execution failed.",
    )

    assert plan.attempt_status == FlowStepAttemptStatus.FAILED
    assert plan.error_code == "step_execution_failed"
    assert plan.error_message == "Flow step 1 execution failed."
    assert plan.failed_result.error_message == "Flow step 1 execution failed."
    assert plan.return_result == {"status": "failed", "error": "step_execution_failed"}


def test_build_step_success_plan_marks_webhook_delivery_requirement():
    claimed = _claimed_result()
    step = _runtime_step(output_mode="http_post")
    output = _step_output()

    plan = build_step_success_plan(
        claimed=claimed,
        run_id=claimed.flow_run_id,
        flow_id=claimed.flow_id,
        tenant_id=claimed.tenant_id,
        step=step,
        output=output,
        output_payload_json={
            "text": "done",
            "generated_file_ids": [],
            "webhook_delivered": False,
        },
        execution_hash="exec-hash",
    )

    assert plan.should_deliver_webhook is True
    assert plan.step_result.status == FlowStepResultStatus.COMPLETED
    assert plan.step_result.output_payload_json == {
        "text": "done",
        "generated_file_ids": [],
        "webhook_delivered": False,
    }


def test_build_step_success_plan_without_webhook_stays_false():
    claimed = _claimed_result()
    step = _runtime_step(output_mode="pass_through")

    plan = build_step_success_plan(
        claimed=claimed,
        run_id=claimed.flow_run_id,
        flow_id=claimed.flow_id,
        tenant_id=claimed.tenant_id,
        step=step,
        output=_step_output(),
        output_payload_json={
            "text": "done",
            "generated_file_ids": [],
            "webhook_delivered": False,
        },
        execution_hash="exec-hash",
    )

    assert plan.should_deliver_webhook is False


def test_build_attempt_provenance_round_trips_all_runtime_sections() -> None:
    claimed = _claimed_result()
    generated_file_id = uuid4()
    step = _runtime_step(input_source="http_post", output_mode="http_post")
    output = _step_output()
    output.generated_file_ids = [generated_file_id]
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
                "artifacts": [
                    {
                        "file_id": str(generated_file_id),
                        "file_name": "answer.docx",
                    }
                ],
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
        "input_source": "http_post",
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
