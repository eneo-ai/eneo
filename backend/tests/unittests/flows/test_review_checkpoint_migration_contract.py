from __future__ import annotations

from sqlalchemy import CheckConstraint

from eneo.database.tables.flow_tables import FlowRunReviewCheckpoints
from eneo.flows.enums import (
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    FlowOutputType,
    FlowRunReviewCheckpointState,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode


def _constraint_sql(name: str) -> str:
    constraint = next(
        constraint
        for constraint in FlowRunReviewCheckpoints.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == name
    )
    return str(constraint.sqltext)


def test_review_checkpoint_constraint_values_match_flow_enums() -> None:
    review_mode_sql = _constraint_sql("ck_flow_run_review_checkpoints_review_mode")
    output_type_sql = _constraint_sql("ck_flow_run_review_checkpoints_output_type")

    assert all(f"'{mode.value}'" in review_mode_sql for mode in FlowStepReviewMode)
    assert all(
        f"'{output_type.value}'" in output_type_sql for output_type in FlowOutputType
    )


def test_review_checkpoint_state_and_expiry_index_match_flow_enums() -> None:
    state_sql = _constraint_sql("ck_flow_run_review_checkpoints_state")
    expiry_index = next(
        index
        for index in FlowRunReviewCheckpoints.__table__.indexes
        if index.name == "ix_flow_run_review_checkpoints_tenant_expires_at_reconcilable"
    )
    predicate = str(expiry_index.dialect_options["postgresql"]["where"])

    assert all(
        f"'{state.value}'" in state_sql for state in FlowRunReviewCheckpointState
    )
    assert {
        state.value
        for state in RECONCILABLE_REVIEW_CHECKPOINT_STATES
        if f"'{state.value}'" in predicate
    } == {state.value for state in RECONCILABLE_REVIEW_CHECKPOINT_STATES}
