from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from intric.flows.flow import FlowStepResult, FlowStepResultStatus
from intric.flows.runtime.claim_resolution import resolve_step_claim
from intric.flows.runtime.models import RunExecutionState


def _result(step_order: int, *, status: FlowStepResultStatus) -> FlowStepResult:
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
        output_payload_json=None,
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


def _state(*, completed_by_order: dict[int, FlowStepResult] | None = None) -> RunExecutionState:
    return RunExecutionState(
        completed_by_order=completed_by_order or {},
        prior_results=[],
        all_previous_segments=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )


def test_resolve_step_claim_returns_proceed_when_claim_succeeds():
    resolution = resolve_step_claim(
        claimed=_result(1, status=FlowStepResultStatus.RUNNING),
        existing=None,
        state=_state(),
    )

    assert resolution.action == "proceed"


def test_resolve_step_claim_returns_missing_when_no_claim_and_no_existing():
    resolution = resolve_step_claim(
        claimed=None,
        existing=None,
        state=_state(),
    )

    assert resolution.action == "missing_step_result"


def test_resolve_step_claim_returns_already_claimed_for_pending_or_running():
    pending = resolve_step_claim(
        claimed=None,
        existing=_result(1, status=FlowStepResultStatus.PENDING),
        state=_state(),
    )
    running = resolve_step_claim(
        claimed=None,
        existing=_result(1, status=FlowStepResultStatus.RUNNING),
        state=_state(),
    )

    assert pending.action == "step_already_claimed"
    assert running.action == "step_already_claimed"


def test_resolve_step_claim_appends_completed_only_when_not_already_in_state():
    completed = _result(2, status=FlowStepResultStatus.COMPLETED)

    append_resolution = resolve_step_claim(
        claimed=None,
        existing=completed,
        state=_state(),
    )
    skip_resolution = resolve_step_claim(
        claimed=None,
        existing=completed,
        state=_state(completed_by_order={2: completed}),
    )

    assert append_resolution.action == "append_completed"
    assert append_resolution.completed_result == completed
    assert skip_resolution.action == "skip"
