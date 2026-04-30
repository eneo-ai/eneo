from __future__ import annotations

from intric.flows.enums import (
    ACTIVE_FLOW_RUN_STATUSES,
    CANCELLABLE_FLOW_RUN_STATUSES,
    TERMINAL_FLOW_RUN_STATUSES,
    FlowRunStatus,
    is_active_flow_run_status,
    is_cancellable_flow_run_status,
    is_terminal_flow_run_status,
)


def test_flow_run_status_sets_partition_current_statuses() -> None:
    assert ACTIVE_FLOW_RUN_STATUSES == {
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
    }
    assert TERMINAL_FLOW_RUN_STATUSES == {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }
    assert CANCELLABLE_FLOW_RUN_STATUSES == ACTIVE_FLOW_RUN_STATUSES
    assert ACTIVE_FLOW_RUN_STATUSES.isdisjoint(TERMINAL_FLOW_RUN_STATUSES)
    assert ACTIVE_FLOW_RUN_STATUSES | TERMINAL_FLOW_RUN_STATUSES == set(FlowRunStatus)


def test_flow_run_status_predicates_accept_enum_and_wire_values() -> None:
    assert is_active_flow_run_status(FlowRunStatus.RUNNING)
    assert is_active_flow_run_status("queued")
    assert is_terminal_flow_run_status(FlowRunStatus.FAILED)
    assert is_terminal_flow_run_status("cancelled")
    assert is_cancellable_flow_run_status(FlowRunStatus.QUEUED)

    assert not is_active_flow_run_status(FlowRunStatus.COMPLETED)
    assert not is_terminal_flow_run_status(FlowRunStatus.RUNNING)
    assert not is_cancellable_flow_run_status(FlowRunStatus.FAILED)
