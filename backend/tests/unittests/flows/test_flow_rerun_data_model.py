from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from intric.database.tables.flow_tables import (
    FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES,
    FLOW_RUN_RERUN_OPERATION_STATUS_VALUES,
    FlowRunRerunInvalidatedSteps,
    FlowRunRerunOperations,
    FlowRuns,
    FlowStepAttempts,
    FlowStepResults,
)
from intric.flows.enums import (
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
)


def _constraint_names(table: object) -> set[str]:
    return {
        constraint.name or ""
        for constraint in table.__table__.constraints
        if constraint.name is not None
    }


def _unique_columns(table: object, constraint_name: str) -> tuple[str, ...]:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.name == constraint_name
        ):
            return tuple(column.name for column in constraint.columns)
    raise AssertionError(f"Unique constraint {constraint_name} was not found.")


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def test_rerun_status_and_role_values_are_canonical_enum_values():
    assert FLOW_RUN_RERUN_OPERATION_STATUS_VALUES == tuple(
        item.value for item in FlowRunRerunOperationStatus
    )
    assert FLOW_RUN_RERUN_INVALIDATION_ROLE_VALUES == tuple(
        item.value for item in FlowRunRerunInvalidationRole
    )


def test_run_revision_and_current_attempt_projection_columns_exist():
    revision = FlowRuns.__table__.columns["revision"]
    current_attempt_no = FlowStepResults.__table__.columns["current_attempt_no"]

    assert revision.nullable is False
    assert str(revision.server_default.arg) == "1"
    assert current_attempt_no.nullable is True
    assert str(current_attempt_no.server_default.arg) == "1"


def test_rerun_operation_table_owns_request_identity_and_status():
    assert {
        "tenant_id",
        "flow_id",
        "flow_run_id",
        "rerun_step_id",
        "root_attempt_no",
        "status",
        "request_fingerprint",
        "expected_run_revision",
        "accepted_run_revision",
        "reason",
        "requested_by_principal_type",
        "requested_by_user_id",
    }.issubset(FlowRunRerunOperations.__table__.columns.keys())
    assert _unique_columns(
        FlowRunRerunOperations,
        "uq_flow_run_rerun_operations_request_fingerprint",
    ) == ("tenant_id", "flow_run_id", "request_fingerprint")
    assert "ck_flow_run_rerun_operations_status" in _constraint_names(
        FlowRunRerunOperations
    )
    assert "requested_by_principal_type = 'user'" in _check_constraint_sql(
        FlowRunRerunOperations,
        "ck_flow_run_rerun_operations_user_principal",
    )
    assert FlowRunRerunOperations.__table__.columns["failure_code"].type.length == 64


def test_new_rerun_foreign_key_names_fit_postgres_identifier_limit():
    new_attempt_fk_columns = {
        "rerun_operation_id",
        "predecessor_attempt_id",
        "superseded_by_attempt_id",
    }
    for table in (
        FlowRunRerunOperations,
        FlowStepAttempts,
        FlowRunRerunInvalidatedSteps,
    ):
        for foreign_key in table.__table__.foreign_key_constraints:
            if table is FlowStepAttempts and not new_attempt_fk_columns.intersection(
                foreign_key.columns.keys()
            ):
                continue
            assert foreign_key.name is not None
            assert len(foreign_key.name) <= 63


def test_step_attempts_have_rerun_lineage_and_payload_snapshots():
    assert {
        "rerun_operation_id",
        "predecessor_attempt_id",
        "superseded_by_attempt_id",
        "input_payload_json",
        "output_payload_json",
        "flow_step_execution_hash",
    }.issubset(FlowStepAttempts.__table__.columns.keys())


def test_invalidated_steps_table_links_operation_and_attempt_lineage():
    assert {
        "operation_id",
        "tenant_id",
        "flow_id",
        "flow_run_id",
        "step_id",
        "invalidation_order",
        "role",
        "dependency_sources_json",
        "prior_step_result_id",
        "prior_attempt_id",
        "new_attempt_no",
        "new_attempt_id",
    }.issubset(FlowRunRerunInvalidatedSteps.__table__.columns.keys())
    assert _unique_columns(
        FlowRunRerunInvalidatedSteps,
        "uq_flow_run_rerun_invalidated_steps_operation_step",
    ) == ("operation_id", "step_id")
    assert _unique_columns(
        FlowRunRerunInvalidatedSteps,
        "uq_flow_run_rerun_invalidated_steps_operation_order",
    ) == ("operation_id", "invalidation_order")
    assert "ck_flow_run_rerun_invalidated_steps_role" in _constraint_names(
        FlowRunRerunInvalidatedSteps
    )
