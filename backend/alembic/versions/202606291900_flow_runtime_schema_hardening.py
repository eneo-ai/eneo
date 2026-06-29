"""harden Flow runtime ordinal constraints and assistant FK indexes

Revision ID: 202606291900_flow_runtime_schema
Revises: 202606281530_builder_state
Create Date: 2026-06-29 19:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from alembic import op

revision = "202606291900_flow_runtime_schema"
down_revision = "202606281530_builder_state"
branch_labels = None
depends_on = None

_ORDINAL_CHECKS: tuple[tuple[str, str, str, str], ...] = (
    (
        "ck_flow_steps_step_order_positive",
        "flow_steps",
        "step_order",
        "step_order >= 1",
    ),
    (
        "ck_flow_step_results_step_order_positive",
        "flow_step_results",
        "step_order",
        "step_order >= 1",
    ),
    (
        "ck_flow_step_results_current_attempt_no_positive",
        "flow_step_results",
        "current_attempt_no",
        "current_attempt_no IS NULL OR current_attempt_no >= 1",
    ),
    (
        "ck_flow_step_attempts_step_order_positive",
        "flow_step_attempts",
        "step_order",
        "step_order >= 1",
    ),
    (
        "ck_flow_step_attempts_attempt_no_positive",
        "flow_step_attempts",
        "attempt_no",
        "attempt_no >= 1",
    ),
)

_ASSISTANT_FK_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    ("ix_flow_steps_assistant_id", "flow_steps", ["assistant_id"]),
    ("ix_flow_step_results_assistant_id", "flow_step_results", ["assistant_id"]),
)


def upgrade() -> None:
    _assert_no_invalid_ordinals()

    for constraint_name, table_name, _, condition in _ORDINAL_CHECKS:
        op.create_check_constraint(constraint_name, table_name, condition)

    for index_name, table_name, columns in _ASSISTANT_FK_INDEXES:
        op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    for index_name, table_name, _ in reversed(_ASSISTANT_FK_INDEXES):
        op.drop_index(index_name, table_name=table_name)

    for constraint_name, table_name, _, _ in reversed(_ORDINAL_CHECKS):
        op.drop_constraint(constraint_name, table_name, type_="check")


def _assert_no_invalid_ordinals() -> None:
    bind = op.get_bind()
    for constraint_name, table_name, column_name, _ in _ORDINAL_CHECKS:
        count = _invalid_ordinal_count(
            bind,
            table_name=table_name,
            column_name=column_name,
        )
        if count == 0:
            continue

        samples = "; ".join(
            _invalid_ordinal_samples(
                bind,
                table_name=table_name,
                column_name=column_name,
            )
        )
        raise RuntimeError(
            f"Cannot add {constraint_name}: {count} {table_name}.{column_name} "
            "rows are less than 1. "
            f"Sample rows: {samples}. "
            "Repair or delete those rows, then rerun the upgrade."
        )


def _invalid_ordinal_count(
    bind: Connection,
    *,
    table_name: str,
    column_name: str,
) -> int:
    count = bind.scalar(
        sa.text(
            f"""
            SELECT count(*)
            FROM {table_name}
            WHERE {column_name} < 1
            """
        )
    )
    return int(count or 0)


def _invalid_ordinal_samples(
    bind: Connection,
    *,
    table_name: str,
    column_name: str,
) -> list[str]:
    rows = bind.execute(
        sa.text(
            f"""
            SELECT id::text AS id, {column_name} AS value
            FROM {table_name}
            WHERE {column_name} < 1
            ORDER BY id
            LIMIT 5
            """
        )
    ).mappings()
    return [f"id={row['id']} {column_name}={row['value']}" for row in rows]
