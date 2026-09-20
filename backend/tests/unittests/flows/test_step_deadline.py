from __future__ import annotations

import pytest

from eneo.flows.runtime import step_deadline as module
from eneo.flows.runtime.step_deadline import (
    StepDeadline,
    current_step_deadline_scope,
    mark_provider_request_in_flight,
    record_step_progress,
    require_step_budget,
    step_deadline_scope,
)
from eneo.main.exceptions import TypedIOValidationException


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    state = {"now": 100.0}
    monkeypatch.setattr(module, "_now", lambda: state["now"])
    return state


@pytest.mark.asyncio
async def test_budget_is_measured_from_start(clock: dict[str, float]) -> None:
    deadline = StepDeadline.start(30)

    clock["now"] = 110.0
    assert deadline.remaining() == 20.0
    assert deadline.elapsed() == 10.0
    assert not deadline.expired()

    clock["now"] = 131.0
    assert deadline.remaining() == 0.0
    assert deadline.expired()


@pytest.mark.asyncio
async def test_boundary_check_reads_the_published_scope(
    clock: dict[str, float],
) -> None:
    """Work the executor cannot reach by parameter (a transcription chunk)
    refuses through the ambient scope, naming the step and the progress."""
    deadline = StepDeadline.start(30)
    assert current_step_deadline_scope() is None
    require_step_budget(phase="anything")  # no scope, no budget: nothing to refuse

    with step_deadline_scope(deadline, step_order=4) as scope:
        assert current_step_deadline_scope() is scope
        record_step_progress("2 of 5 items completed")
        require_step_budget(phase="transcription chunk 3")
        clock["now"] = 131.0
        with pytest.raises(TypedIOValidationException) as exc_info:
            require_step_budget(phase="transcription chunk 3")
    assert current_step_deadline_scope() is None

    assert exc_info.value.code == "flow_step_timeout"
    message = str(exc_info.value)
    assert message.startswith(
        "Step 4: execution budget of 30s exhausted during transcription chunk 3"
    )
    assert "2 of 5 items completed" in message
    assert "may still complete" not in message


@pytest.mark.asyncio
async def test_timeout_message_reports_the_in_flight_request_from_scope(
    clock: dict[str, float],
) -> None:
    deadline = StepDeadline.start(30)
    with step_deadline_scope(deadline, step_order=1):
        mark_provider_request_in_flight(True)
        clock["now"] = 140.0
        error = deadline.timeout_error(step_order=1, phase="step execution")
        mark_provider_request_in_flight(False)
        quiet = deadline.timeout_error(step_order=1, phase="step execution")

    assert "provider may still complete" in str(error)
    assert "provider may still complete" not in str(quiet)


@pytest.mark.asyncio
@pytest.mark.parametrize("completed", [0, 1])
async def test_timeout_carries_observed_phase_and_mapped_progress(clock, completed):
    from eneo.flows.enums import FlowStepPhase

    deadline = StepDeadline.start(30)
    with step_deadline_scope(deadline, step_order=2) as scope:
        scope.phase = FlowStepPhase.PROVIDER_REQUEST
        scope.completed_items = completed
        scope.total_items = 3
        mark_provider_request_in_flight(True)
        clock["now"] = 131.0
        error = deadline.timeout_error(step_order=2, phase="step execution")
    assert error.step_phase is FlowStepPhase.PROVIDER_REQUEST
    assert error.completed_items == completed
    assert error.total_items == 3
    assert error.provider_work_may_have_completed is True


def test_timeout_does_not_infer_structured_phase_from_prose(clock):
    error = StepDeadline.start(30).timeout_error(step_order=1, phase="provider request")
    assert error.step_phase is None
    assert error.completed_items is None
    assert error.total_items is None
    assert error.provider_work_may_have_completed is None
