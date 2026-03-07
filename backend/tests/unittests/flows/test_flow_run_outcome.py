from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.runtime.run_outcome import determine_run_outcome


def _result(step_order: int, *, status: FlowStepResultStatus, text: str = "") -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        input_payload_json=None,
        effective_prompt=None,
        output_payload_json={"text": text} if text else None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=status,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )


def test_determine_run_outcome_prefers_failed_results():
    outcome = determine_run_outcome(
        results=[
            _result(1, status=FlowStepResultStatus.COMPLETED, text="ok"),
            _result(2, status=FlowStepResultStatus.FAILED),
        ]
    )

    assert outcome.result_status == "failed"
    assert outcome.flow_status == "failed"
    assert outcome.error_message == "One or more flow steps failed."


def test_determine_run_outcome_returns_skipped_for_in_progress_runs():
    outcome = determine_run_outcome(
        results=[
            _result(1, status=FlowStepResultStatus.COMPLETED, text="ok"),
            _result(2, status=FlowStepResultStatus.RUNNING),
        ]
    )

    assert outcome.result_status == "skipped"
    assert outcome.reason == "run_in_progress"


def test_determine_run_outcome_returns_latest_completed_payload():
    outcome = determine_run_outcome(
        results=[
            _result(1, status=FlowStepResultStatus.COMPLETED, text="older"),
            _result(2, status=FlowStepResultStatus.COMPLETED, text="newest"),
        ]
    )

    assert outcome.result_status == "completed"
    assert outcome.flow_status == "completed"
    assert outcome.output_payload_json == {"text": "newest"}


def test_determine_run_outcome_returns_cancelled_when_any_step_cancelled():
    outcome = determine_run_outcome(
        results=[
            _result(1, status=FlowStepResultStatus.COMPLETED, text="ok"),
            _result(2, status=FlowStepResultStatus.CANCELLED),
        ]
    )

    assert outcome.result_status == "cancelled"
    assert outcome.flow_status == "cancelled"
    assert outcome.error_message == "One or more steps were cancelled."


def test_determine_run_outcome_handles_empty_results_as_completed_without_payload():
    outcome = determine_run_outcome(results=[])

    assert outcome.result_status == "completed"
    assert outcome.flow_status == "completed"
    assert outcome.output_payload_json is None
