from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint

from intric.database.tables.flow_tables import FlowRunStepResultFiles


def _foreign_key_constraint(name: str) -> ForeignKeyConstraint:
    for constraint in FlowRunStepResultFiles.__table__.constraints:
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name:
            return constraint
    raise AssertionError(f"Foreign key constraint {name} was not found.")


def test_step_result_files_reference_step_attempt_natural_key() -> None:
    assert FlowRunStepResultFiles.__table__.columns["attempt_no"].server_default is None
    constraint = _foreign_key_constraint("fk_flow_run_step_result_files_step_attempt")

    assert tuple(column.name for column in constraint.columns) == (
        "flow_run_id",
        "step_id",
        "attempt_no",
    )
    assert tuple(element.column.table.name for element in constraint.elements) == (
        "flow_step_attempts",
        "flow_step_attempts",
        "flow_step_attempts",
    )
    assert tuple(element.column.name for element in constraint.elements) == (
        "flow_run_id",
        "step_id",
        "attempt_no",
    )
    assert constraint.ondelete == "CASCADE"
