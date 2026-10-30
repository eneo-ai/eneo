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
    FlowStepResultAnnotation,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.run_outcome import (
    determine_run_outcome,
    finalize_run_from_current_results,
)

COMPLETED = FlowStepResultStatus.COMPLETED
FAILED = FlowStepResultStatus.FAILED
CANCELLED = FlowStepResultStatus.CANCELLED
PENDING = FlowStepResultStatus.PENDING
RUNNING = FlowStepResultStatus.RUNNING


def _status(step_order: int, status: FlowStepResultStatus) -> FlowStepResultAnnotation:
    return FlowStepResultAnnotation(
        step_id=uuid4(), step_order=step_order, status=status
    )


def _statuses(*statuses: FlowStepResultStatus) -> list[FlowStepResultAnnotation]:
    return [_status(order, status) for order, status in enumerate(statuses, start=1)]


class RecordingStepResultReads:
    """The two step-result reads finalization may make, and what it asked."""

    def __init__(
        self,
        statuses: list[FlowStepResultAnnotation],
        *,
        last_completed_output: FlowPersistedJsonObject | None = None,
    ) -> None:
        self.statuses = statuses
        self.last_completed_output = last_completed_output
        self.annotation_reads: list[tuple[UUID, UUID]] = []
        self.payload_reads: list[tuple[UUID, UUID]] = []

    async def list_step_result_annotations(
        self, *, run_id: UUID, tenant_id: UUID
    ) -> list[FlowStepResultAnnotation]:
        self.annotation_reads.append((run_id, tenant_id))
        return self.statuses

    async def read_last_completed_output_payload(
        self, *, run_id: UUID, tenant_id: UUID
    ) -> FlowPersistedJsonObject | None:
        self.payload_reads.append((run_id, tenant_id))
        return self.last_completed_output


class RecordingTerminalizer:
    def __init__(self) -> None:
        self.calls = 0
        self.error: FlowRunError | None = None
        self.target_status: FlowRunStatus | None = None
        self.source: FlowRunLifecycleSource | None = None
        self.output_payload_json: FlowPersistedJsonObject | None = None

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
        self.calls += 1
        self.error = error
        self.target_status = target_status
        self.source = source
        self.output_payload_json = output_payload_json
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


async def _finalize(
    reads: RecordingStepResultReads,
    terminalizer: RecordingTerminalizer,
    *,
    run_id: UUID | None = None,
    tenant_id: UUID | None = None,
):
    return await finalize_run_from_current_results(
        run_id=run_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        flow_run_repo=cast(FlowRunRepository, reads),
        terminalizer=cast(FlowRunTerminalizer, terminalizer),
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        pytest.param((COMPLETED, FAILED), "failed", id="failed-over-completed"),
        pytest.param((FAILED, PENDING), "failed", id="failed-over-pending"),
        pytest.param((RUNNING, FAILED), "failed", id="failed-over-running"),
        pytest.param((CANCELLED, FAILED), "failed", id="failed-over-cancelled"),
        pytest.param((COMPLETED, PENDING), "skipped", id="pending-over-completed"),
        pytest.param((RUNNING, COMPLETED), "skipped", id="running-over-completed"),
        pytest.param((CANCELLED, PENDING), "skipped", id="pending-over-cancelled"),
        pytest.param(
            (COMPLETED, CANCELLED), "cancelled", id="cancelled-over-completed"
        ),
        pytest.param((CANCELLED, COMPLETED), "cancelled", id="earlier-cancelled"),
        pytest.param((COMPLETED, COMPLETED), "completed", id="all-completed"),
        pytest.param((), "completed", id="no-steps"),
    ],
)
def test_determine_run_outcome_keeps_its_precedence(
    statuses: tuple[FlowStepResultStatus, ...], expected: str
):
    outcome = determine_run_outcome(statuses=_statuses(*statuses))

    assert outcome.result_status == expected


def test_determine_run_outcome_names_each_terminal_outcome():
    failed = determine_run_outcome(statuses=_statuses(COMPLETED, FAILED))
    cancelled = determine_run_outcome(statuses=_statuses(COMPLETED, CANCELLED))
    skipped = determine_run_outcome(statuses=_statuses(COMPLETED, RUNNING))
    completed = determine_run_outcome(statuses=_statuses(COMPLETED))

    assert (failed.flow_status, failed.error_code, failed.error_message) == (
        "failed",
        FlowApiErrorCode.STEP_EXECUTION_FAILED,
        "One or more flow steps failed.",
    )
    assert (cancelled.flow_status, cancelled.error_code, cancelled.error_message) == (
        "cancelled",
        FlowApiErrorCode.RUN_CANCELLED,
        "One or more steps were cancelled.",
    )
    assert (skipped.flow_status, skipped.reason) == (None, "run_in_progress")
    assert (completed.flow_status, completed.error_code) == ("completed", None)


@pytest.mark.asyncio
async def test_a_completed_run_returns_the_last_completed_output():
    run_id, tenant_id = uuid4(), uuid4()
    reads = RecordingStepResultReads(
        _statuses(COMPLETED, COMPLETED),
        last_completed_output={"text": "newest"},
    )
    terminalizer = RecordingTerminalizer()

    result = await _finalize(reads, terminalizer, run_id=run_id, tenant_id=tenant_id)

    assert result.payload == {"status": "completed"}
    assert reads.annotation_reads == [(run_id, tenant_id)]
    assert reads.payload_reads == [(run_id, tenant_id)]
    assert terminalizer.target_status == FlowRunStatus.COMPLETED
    assert terminalizer.source == FlowRunLifecycleSource.EXECUTOR_COMPLETED
    assert terminalizer.error is None
    assert terminalizer.output_payload_json == {"text": "newest"}


@pytest.mark.asyncio
async def test_a_run_without_steps_completes_without_an_output():
    reads = RecordingStepResultReads([])
    terminalizer = RecordingTerminalizer()

    result = await _finalize(reads, terminalizer)

    assert result.payload == {"status": "completed"}
    assert terminalizer.target_status == FlowRunStatus.COMPLETED
    assert terminalizer.output_payload_json is None


@pytest.mark.parametrize(
    ("statuses", "target_status", "error_code"),
    [
        pytest.param(
            (COMPLETED, FAILED),
            FlowRunStatus.FAILED,
            FlowApiErrorCode.STEP_EXECUTION_FAILED,
            id="failed",
        ),
        # A later cancelled step cancels the run: no completed output is read.
        pytest.param(
            (COMPLETED, CANCELLED),
            FlowRunStatus.CANCELLED,
            FlowApiErrorCode.RUN_CANCELLED,
            id="cancelled",
        ),
    ],
)
@pytest.mark.asyncio
async def test_a_failed_or_cancelled_run_never_reads_a_step_output(
    statuses: tuple[FlowStepResultStatus, ...],
    target_status: FlowRunStatus,
    error_code: FlowApiErrorCode,
):
    reads = RecordingStepResultReads(
        _statuses(*statuses), last_completed_output={"text": "unread"}
    )
    terminalizer = RecordingTerminalizer()

    result = await _finalize(reads, terminalizer)

    assert result.payload == {"status": target_status.value}
    assert reads.payload_reads == []
    assert terminalizer.target_status == target_status
    assert terminalizer.source == FlowRunLifecycleSource.EXECUTOR_FAILED
    assert terminalizer.error is not None
    assert terminalizer.error.code == error_code.value
    assert terminalizer.output_payload_json is None


@pytest.mark.asyncio
async def test_a_run_in_progress_is_left_running_without_reading_an_output():
    reads = RecordingStepResultReads(
        _statuses(COMPLETED, PENDING), last_completed_output={"text": "unread"}
    )
    terminalizer = RecordingTerminalizer()

    result = await _finalize(reads, terminalizer)

    assert result.payload == {"status": "skipped", "reason": "run_in_progress"}
    assert result.terminalization is None
    assert reads.payload_reads == []
    assert terminalizer.calls == 0
