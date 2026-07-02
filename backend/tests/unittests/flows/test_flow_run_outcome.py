from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

import pytest

from eneo.flows.application.flow_run_terminalization import (
    FlowRunTerminalizationResult,
    FlowRunTerminalizer,
)
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.run_outcome import (
    determine_run_outcome,
    finalize_run_from_current_results,
)


def _result(
    step_order: int, *, status: FlowStepResultStatus, text: str = ""
) -> FlowStepResult:
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
        created_at=now,
        updated_at=now,
    )


class RecordingTerminalizer:
    def __init__(self) -> None:
        self.error: FlowRunError | None = None
        self.target_status: FlowRunStatus | None = None
        self.source: FlowRunLifecycleSource | None = None

    async def terminalize_run(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        target_status: FlowRunStatus,
        source: FlowRunLifecycleSource,
        error: FlowRunError | None = None,
        output_payload_json: FlowPersistedJsonObject | None = None,
        cancelled_at: datetime | None = None,
        principal: FlowPrincipal | None = None,
    ) -> FlowRunTerminalizationResult:
        _ = (cancelled_at, principal)
        now = datetime.now(timezone.utc)
        self.error = error
        self.target_status = target_status
        self.source = source
        return FlowRunTerminalizationResult(
            run=FlowRun(
                id=run_id,
                flow_id=uuid4(),
                flow_version=1,
                tenant_id=tenant_id,
                trace_id=uuid4(),
                status=target_status,
                output_payload_json=output_payload_json,
                error=error,
                created_at=now,
                updated_at=now,
            ),
            did_transition=True,
            target_status=target_status,
            source=source,
            audit_outbox_id=None,
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


@pytest.mark.parametrize(
    "active_status",
    [
        FlowStepResultStatus.PENDING,
        FlowStepResultStatus.RUNNING,
    ],
)
def test_determine_run_outcome_returns_skipped_for_in_progress_runs(
    active_status: FlowStepResultStatus,
):
    outcome = determine_run_outcome(
        results=[
            _result(1, status=FlowStepResultStatus.COMPLETED, text="ok"),
            _result(2, status=active_status),
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


@pytest.mark.asyncio
async def test_finalize_run_from_current_results_uses_cancelled_run_error_code():
    terminalizer = RecordingTerminalizer()

    result = await finalize_run_from_current_results(
        run_id=uuid4(),
        tenant_id=uuid4(),
        results=[_result(1, status=FlowStepResultStatus.CANCELLED)],
        terminalizer=cast(FlowRunTerminalizer, terminalizer),
    )

    assert result.terminalization is not None
    assert result.terminalization.run.status == FlowRunStatus.CANCELLED
    assert terminalizer.target_status == FlowRunStatus.CANCELLED
    assert terminalizer.source == FlowRunLifecycleSource.EXECUTOR_FAILED
    assert terminalizer.error is not None
    assert terminalizer.error.code == FlowApiErrorCode.RUN_CANCELLED.value
