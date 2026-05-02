from __future__ import annotations

from sqlalchemy import CheckConstraint, Index

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.category_mappings import CATEGORY_MAPPINGS
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.flow_tables import (
    FLOW_RUN_ACTIVE_REVIEW_CHECKPOINT_STATE_VALUES,
    FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES,
    FLOW_RUN_AUDIT_TARGET_STATUS_VALUES,
    FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES,
    FLOW_RUN_STATUS_VALUES,
    FlowRunAuditOutbox,
    FlowRunReviewCheckpoints,
    FlowRuns,
)
from intric.flows.enums import (
    ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
)


def _constraint_names(table: object) -> set[str]:
    return {
        constraint.name or ""
        for constraint in table.__table__.constraints
        if constraint.name is not None
    }


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def _index_by_name(table: object, index_name: str) -> Index:
    for index in table.__table__.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"Index {index_name} was not found.")


def test_review_checkpoint_status_values_are_canonical_enum_values() -> None:
    assert FlowRunStatus.AWAITING_REVIEW.value == "awaiting_review"
    assert FlowRunStatus.AWAITING_REVIEW.value in FLOW_RUN_STATUS_VALUES
    assert FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES == tuple(
        item.value for item in FlowRunReviewCheckpointState
    )
    assert FLOW_RUN_ACTIVE_REVIEW_CHECKPOINT_STATE_VALUES == (
        FlowRunReviewCheckpointState.AWAITING_REVIEW.value,
        FlowRunReviewCheckpointState.EDITED.value,
        FlowRunReviewCheckpointState.APPROVED.value,
    )
    assert ACTIVE_FLOW_RUN_REVIEW_CHECKPOINT_STATES == {
        FlowRunReviewCheckpointState.AWAITING_REVIEW,
        FlowRunReviewCheckpointState.EDITED,
        FlowRunReviewCheckpointState.APPROVED,
    }


def test_review_lifecycle_audit_vocabulary_is_explicit() -> None:
    review_actions = {
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EDITED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_APPROVED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_REJECTED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_RESUMED,
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED,
    }

    assert EntityType.FLOW_RUN_REVIEW_CHECKPOINT.value == "flow_run_review_checkpoint"
    assert {
        FlowRunLifecycleSource.REVIEW_REJECTED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_OPENED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_EDITED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_APPROVED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_REJECTED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_RESUMED.value,
        FlowRunLifecycleSource.REVIEW_CHECKPOINT_CANCELLED.value,
    }.issubset({item.value for item in FlowRunLifecycleSource})
    assert {CATEGORY_MAPPINGS[action.value] for action in review_actions} == {
        "user_actions"
    }


def test_flow_run_status_constraint_accepts_awaiting_review() -> None:
    status_constraint = _check_constraint_sql(FlowRuns, "ck_flow_runs_status")

    assert "awaiting_review" in status_constraint
    assert "queued" in status_constraint
    assert "completed" in status_constraint


def test_review_checkpoint_table_owns_state_payloads_and_resume_key() -> None:
    columns = FlowRunReviewCheckpoints.__table__.columns

    assert {
        "tenant_id",
        "flow_id",
        "flow_run_id",
        "step_id",
        "step_order",
        "attempt_no",
        "state",
        "revision",
        "schema_version",
        "original_payload_json",
        "current_payload_json",
        "requester_user_id",
        "requester_principal_type",
        "decided_by_user_id",
        "decided_by_principal_type",
        "next_step_ids_json",
        "resume_idempotency_key",
        "edited_at",
        "approved_at",
        "rejected_at",
        "resumed_at",
        "cancelled_at",
    }.issubset(columns.keys())
    assert columns["state"].server_default.arg == "awaiting_review"
    assert str(columns["revision"].server_default.arg) == "1"
    assert str(columns["schema_version"].server_default.arg) == "1"
    assert "ck_flow_run_review_checkpoints_state" in _constraint_names(
        FlowRunReviewCheckpoints
    )
    assert "ck_flow_run_review_checkpoints_requester_principal" in _constraint_names(
        FlowRunReviewCheckpoints
    )

    active_index = _index_by_name(
        FlowRunReviewCheckpoints,
        "uq_flow_run_review_checkpoints_one_active_per_run",
    )
    assert active_index.unique is True
    assert tuple(column.name for column in active_index.columns) == ("flow_run_id",)
    assert (
        str(active_index.dialect_options["postgresql"]["where"])
        == "state IN ('awaiting_review', 'edited', 'approved')"
    )

    resume_index = _index_by_name(
        FlowRunReviewCheckpoints,
        "uq_flow_run_review_checkpoints_resume_key",
    )
    assert resume_index.unique is True
    assert tuple(column.name for column in resume_index.columns) == (
        "tenant_id",
        "flow_run_id",
        "resume_idempotency_key",
    )
    assert (
        str(resume_index.dialect_options["postgresql"]["where"])
        == "resume_idempotency_key IS NOT NULL"
    )


def test_review_audit_outbox_uses_checkpoint_revision_key() -> None:
    columns = FlowRunAuditOutbox.__table__.columns

    assert {"review_checkpoint_id", "checkpoint_revision"}.issubset(columns.keys())
    assert {
        "delivery_status",
        "delivery_attempts",
        "next_delivery_at",
        "delivered_at",
        "dead_lettered_at",
        "delivery_last_error",
    }.issubset(columns.keys())
    assert "ck_flow_run_audit_outbox_checkpoint_key" in _constraint_names(
        FlowRunAuditOutbox
    )
    assert "ck_flow_run_audit_outbox_delivery_attempts" in _constraint_names(
        FlowRunAuditOutbox
    )
    assert "ck_flow_run_audit_outbox_delivery_status" in _constraint_names(
        FlowRunAuditOutbox
    )
    assert "ck_flow_run_audit_outbox_delivery_timestamps" in _constraint_names(
        FlowRunAuditOutbox
    )
    assert FLOW_RUN_AUDIT_OUTBOX_DELIVERY_STATUS_VALUES == (
        "pending",
        "delivered",
        "dead_lettered",
    )
    assert "dead_lettered" in _check_constraint_sql(
        FlowRunAuditOutbox,
        "ck_flow_run_audit_outbox_delivery_status",
    )
    assert "awaiting_review" in _check_constraint_sql(
        FlowRunAuditOutbox,
        "ck_flow_run_audit_outbox_target_status",
    )
    assert set(FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES).issubset(
        set(FLOW_RUN_AUDIT_TARGET_STATUS_VALUES)
    )
    assert "resumed" in FLOW_RUN_AUDIT_TARGET_STATUS_VALUES
    assert "review_checkpoint_opened" in _check_constraint_sql(
        FlowRunAuditOutbox,
        "ck_flow_run_audit_outbox_source",
    )

    terminal_index = _index_by_name(
        FlowRunAuditOutbox,
        "uq_flow_run_audit_outbox_run_revision",
    )
    assert terminal_index.unique is True
    assert tuple(column.name for column in terminal_index.columns) == (
        "flow_run_id",
        "run_revision",
    )
    assert (
        str(terminal_index.dialect_options["postgresql"]["where"])
        == "review_checkpoint_id IS NULL"
    )

    checkpoint_index = _index_by_name(
        FlowRunAuditOutbox,
        "uq_flow_run_audit_outbox_checkpoint_revision",
    )
    assert checkpoint_index.unique is True
    assert tuple(column.name for column in checkpoint_index.columns) == (
        "review_checkpoint_id",
        "checkpoint_revision",
    )
    assert (
        str(checkpoint_index.dialect_options["postgresql"]["where"])
        == "review_checkpoint_id IS NOT NULL"
    )

    pending_delivery_index = _index_by_name(
        FlowRunAuditOutbox,
        "ix_flow_run_audit_outbox_pending_delivery",
    )
    assert tuple(column.name for column in pending_delivery_index.columns) == (
        "next_delivery_at",
        "created_at",
    )
    assert (
        str(pending_delivery_index.dialect_options["postgresql"]["where"])
        == "delivery_status = 'pending'"
    )

    dead_lettered_index = _index_by_name(
        FlowRunAuditOutbox,
        "ix_flow_run_audit_outbox_dead_lettered",
    )
    assert tuple(column.name for column in dead_lettered_index.columns) == (
        "dead_lettered_at",
    )
    assert (
        str(dead_lettered_index.dialect_options["postgresql"]["where"])
        == "delivery_status = 'dead_lettered'"
    )
