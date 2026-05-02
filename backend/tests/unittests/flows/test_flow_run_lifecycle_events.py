from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.flows.application.flow_run_lifecycle_events import (
    FLOW_RUN_LIFECYCLE_EVENT_NAME,
    FLOW_RUN_LIFECYCLE_EVENT_SCHEMA_VERSION,
    FLOW_RUN_TERMINALIZATION_OPERATION,
    FlowRunTerminalizationOutcome,
    emit_flow_run_terminalization_event,
)
from intric.flows.domain.flow import FlowRun, FlowRunStatus
from intric.flows.enums import FlowRunLifecycleSource

LIFECYCLE_LOGGER = "intric.flows.application.flow_run_lifecycle_events"


def _run() -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        revision=4,
        status=FlowRunStatus.FAILED,
        cancelled_at=None,
        input_payload_json={"question": "What happened?"},
        output_payload_json=None,
        error_message="flow_worker_stalled: stale run reconciled.",
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _lifecycle_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == FLOW_RUN_LIFECYCLE_EVENT_NAME
    ]


def test_emit_flow_run_terminalization_event_uses_stable_schema(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LIFECYCLE_LOGGER)
    run = _run()
    outbox_id = uuid4()

    emit_flow_run_terminalization_event(
        run=run,
        outcome="transitioned",
        source=FlowRunLifecycleSource.STALE_RUNNING_RECONCILER,
        target_status=FlowRunStatus.FAILED,
        previous_status=FlowRunStatus.RUNNING,
        audit_outbox_id=outbox_id,
        error_code="flow_worker_stalled",
    )

    records = _lifecycle_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.message == "flow_run_lifecycle_event"
    assert getattr(record, "schema_version") == FLOW_RUN_LIFECYCLE_EVENT_SCHEMA_VERSION
    assert getattr(record, "operation") == FLOW_RUN_TERMINALIZATION_OPERATION
    assert getattr(record, "outcome") == "transitioned"
    assert getattr(record, "tenant_id") == str(run.tenant_id)
    assert getattr(record, "flow_id") == str(run.flow_id)
    assert getattr(record, "run_id") == str(run.id)
    assert getattr(record, "trace_id") == str(run.trace_id)
    assert (
        getattr(record, "source")
        == FlowRunLifecycleSource.STALE_RUNNING_RECONCILER.value
    )
    assert getattr(record, "target_status") == FlowRunStatus.FAILED.value
    assert getattr(record, "previous_status") == FlowRunStatus.RUNNING.value
    assert getattr(record, "run_revision") == run.revision
    assert getattr(record, "audit_outbox_id") == str(outbox_id)
    assert getattr(record, "error_code") == "flow_worker_stalled"


def _assert_noop_event_payload(
    *,
    caplog: pytest.LogCaptureFixture,
    outcome: FlowRunTerminalizationOutcome,
) -> None:
    caplog.set_level(logging.INFO, logger=LIFECYCLE_LOGGER)
    run = _run()

    emit_flow_run_terminalization_event(
        run=run,
        outcome=outcome,
        source=FlowRunLifecycleSource.TASK_FAILURE,
        target_status=FlowRunStatus.FAILED,
        previous_status=FlowRunStatus.RUNNING,
        audit_outbox_id=None,
        error_code="flow_task_failure",
    )

    records = _lifecycle_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "outcome") == outcome
    assert getattr(record, "target_status") == FlowRunStatus.FAILED.value
    assert getattr(record, "previous_status") == FlowRunStatus.RUNNING.value
    assert getattr(record, "audit_outbox_id") is None
    assert getattr(record, "error_code") == "flow_task_failure"


def test_emit_flow_run_terminalization_event_noop_already_terminal_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _assert_noop_event_payload(
        caplog=caplog,
        outcome="noop_already_terminal",
    )


def test_emit_flow_run_terminalization_event_noop_lost_race_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _assert_noop_event_payload(
        caplog=caplog,
        outcome="noop_lost_race",
    )
