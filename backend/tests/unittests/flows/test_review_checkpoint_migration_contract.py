from __future__ import annotations

from pathlib import Path
from runpy import run_path

from intric.flows.enums import (
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunReviewCheckpointState,
)
from intric.flows.flow_review_policy import FlowStepReviewMode


def test_review_checkpoint_snapshot_migration_constraint_values_match_flow_enums() -> (
    None
):
    migration_path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "20260508_review_checkpoint_contract_snapshot.py"
    )
    migration = run_path(str(migration_path))

    assert tuple(migration["REVIEW_CHECKPOINT_REVIEW_MODE_VALUES"]) == tuple(
        mode.value for mode in FlowStepReviewMode
    )
    assert tuple(migration["REVIEW_CHECKPOINT_OUTPUT_TYPE_VALUES"]) == tuple(
        output_type.value for output_type in FlowOutputType
    )


def test_review_checkpoint_expiry_migration_constraint_values_match_flow_enums() -> (
    None
):
    migration_path = (
        Path(__file__).parents[3] / "alembic" / "versions" / "20260514_review_expiry.py"
    )
    migration = run_path(str(migration_path))

    assert len(migration["revision"]) <= 32
    assert tuple(migration["REVIEW_CHECKPOINT_STATES"]) == tuple(
        state.value for state in FlowRunReviewCheckpointState
    )
    assert set(migration["REVIEW_CHECKPOINT_RECONCILABLE_STATES"]) == {
        state.value for state in RECONCILABLE_REVIEW_CHECKPOINT_STATES
    }
    assert tuple(migration["FLOW_RUN_LIFECYCLE_SOURCES"]) == tuple(
        source.value for source in FlowRunLifecycleSource
    )
    assert (
        migration["REVIEW_CHECKPOINT_EXPIRY_INDEX_PREDICATE"]
        == "state IN ('awaiting_review', 'edited')"
    )
