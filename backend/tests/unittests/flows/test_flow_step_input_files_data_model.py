from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from eneo.database.tables.flow_tables import (
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
)


def _check_constraint_sql(constraint_name: str) -> str:
    for constraint in FlowRunStepInputFiles.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def _check_constraint_names() -> set[str]:
    return {
        constraint.name
        for constraint in FlowRunStepInputFiles.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _foreign_key_names(table) -> set[str]:
    return {
        constraint.name
        for constraint in table.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None
    }


def _unique_constraint_names(table) -> set[str]:
    return {
        constraint.name
        for constraint in table.__table__.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name is not None
    }


def test_step_input_files_enforce_positive_attempt_projection() -> None:
    assert FlowRunStepInputFiles.__table__.columns["attempt_no"].server_default is None
    assert (
        _check_constraint_sql("ck_flow_run_step_input_files_attempt_no_positive")
        == "attempt_no >= 1"
    )
    assert (
        "ck_flow_run_step_input_files_attempt_no_initial"
        not in _check_constraint_names()
    )


def test_step_input_files_require_runtime_upload_binding() -> None:
    assert "fk_flow_run_step_input_files_runtime_upload" in _foreign_key_names(
        FlowRunStepInputFiles
    )


def test_runtime_uploaded_files_expose_composite_fk_target() -> None:
    assert (
        "uq_flow_runtime_uploaded_files_file_flow_tenant"
        in _unique_constraint_names(FlowRuntimeUploadedFiles)
    )
    assert "fk_flow_runtime_uploaded_files_flow_tenant" in _foreign_key_names(
        FlowRuntimeUploadedFiles
    )
