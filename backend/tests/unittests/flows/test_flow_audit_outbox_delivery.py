from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.flows.application.flow_run_audit_outbox_delivery import (
    build_audit_log_from_outbox,
)
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS,
    flow_audit_outbox_retry_delay_seconds,
)
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxDeliveryRow,
)


def _outbox_row(
    *,
    action: str = ActionType.FLOW_RUN_COMPLETED.value,
    source: str = "executor_completed",
    target_status: str = "completed",
    error_code: str | None = None,
    error_message: str | None = None,
) -> FlowRunAuditOutboxDeliveryRow:
    run_id = uuid4()
    return FlowRunAuditOutboxDeliveryRow(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=run_id,
        run_revision=2,
        review_checkpoint_id=None,
        checkpoint_revision=None,
        description=f"{action}:{source}",
        action=action,
        entity_type=EntityType.FLOW_RUN.value,
        entity_id=run_id,
        actor_id=uuid4(),
        actor_type=ActorType.USER.value,
        actor_api_key_id=None,
        source=source,
        target_status=target_status,
        error_code=error_code,
        error_message=error_message,
        created_at=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        delivery_attempts=0,
    )


@pytest.mark.parametrize(
    ("action", "source", "expected_description"),
    [
        (
            ActionType.FLOW_RUN_COMPLETED.value,
            "executor_completed",
            "Flow run completed by executor_completed.",
        ),
        (
            ActionType.FLOW_RUN_FAILED.value,
            "task_timeout",
            "Flow run failed by task_timeout.",
        ),
        (
            ActionType.FLOW_RUN_CANCELLED.value,
            "user_cancel",
            "Flow run cancelled by user_cancel.",
        ),
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED.value,
            "review_policy",
            "Flow run review checkpoint opened by review_policy.",
        ),
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EDITED.value,
            "review_edited",
            "Flow run review checkpoint edited by review_edited.",
        ),
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_APPROVED.value,
            "review_approved",
            "Flow run review checkpoint approved by review_approved.",
        ),
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_REJECTED.value,
            "review_rejected",
            "Flow run review checkpoint rejected by review_rejected.",
        ),
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_RESUMED.value,
            "review_resumed",
            "Flow run review checkpoint resumed by review_resumed.",
        ),
        (
            ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED.value,
            "review_cancelled",
            "Flow run review checkpoint cancelled by review_cancelled.",
        ),
    ],
)
def test_flow_audit_outbox_description_mapping_is_complete(
    action: str,
    source: str,
    expected_description: str,
) -> None:
    row = _outbox_row(action=action, source=source)

    audit_log = build_audit_log_from_outbox(row)

    assert audit_log.description == expected_description


def test_completed_run_outbox_builds_human_audit_log_description() -> None:
    row = _outbox_row()

    audit_log = build_audit_log_from_outbox(row)

    assert audit_log.id == row.id
    assert audit_log.description == "Flow run completed by executor_completed."
    assert audit_log.outcome == Outcome.SUCCESS
    assert audit_log.error_message is None
    assert audit_log.metadata == {
        "flow_id": str(row.flow_id),
        "flow_run_id": str(row.flow_run_id),
        "run_revision": 2,
        "source": "executor_completed",
        "target_status": "completed",
        "review_checkpoint_id": None,
        "checkpoint_revision": None,
        "error_code": None,
        "outbox_description": "flow_run_completed:executor_completed",
    }


def test_failed_run_outbox_uses_non_empty_error_message_fallback() -> None:
    row = _outbox_row(
        action=ActionType.FLOW_RUN_FAILED.value,
        source="task_timeout",
        target_status="failed",
    )

    audit_log = build_audit_log_from_outbox(row)

    assert audit_log.description == "Flow run failed by task_timeout."
    assert audit_log.outcome == Outcome.FAILURE
    assert audit_log.error_message == "flow_run_failed:task_timeout"


@pytest.mark.parametrize(
    ("error_message", "error_code", "expected_error_message"),
    [
        ("explicit failure", "flow_task_failure", "explicit failure"),
        (" ", "flow_task_failure", "flow_task_failure"),
        (None, None, "flow_run_failed:task_timeout"),
    ],
)
def test_failed_run_outbox_error_message_fallback_order(
    error_message: str | None,
    error_code: str | None,
    expected_error_message: str,
) -> None:
    row = _outbox_row(
        action=ActionType.FLOW_RUN_FAILED.value,
        source="task_timeout",
        target_status="failed",
        error_code=error_code,
        error_message=error_message,
    )

    audit_log = build_audit_log_from_outbox(row)

    assert audit_log.error_message == expected_error_message


def test_retry_policy_dead_letters_at_max_attempts() -> None:
    assert flow_audit_outbox_retry_delay_seconds(failed_attempt_no=1) == 60
    assert (
        flow_audit_outbox_retry_delay_seconds(
            failed_attempt_no=FLOW_AUDIT_OUTBOX_MAX_ATTEMPTS
        )
        is None
    )
