"""Bound Flow attempt evidence admission by runtime ordering indexes.

Revision ID: 202607291800_attempt_admit_idx
Revises: 202607271700_call_input_indexes
Create Date: 2026-07-29 18:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "202607291800_attempt_admit_idx"
down_revision = "202607271700_call_input_indexes"
branch_labels = None
depends_on = None

_ATTEMPT_INDEX = "ix_flow_step_attempts_run_step_order_attempt"
_ATTEMPT_TABLE = "flow_step_attempts"
_ATTEMPT_COLUMNS = ("flow_run_id", "step_order", "attempt_no")
_RESULT_INDEX = "ix_flow_step_results_run_step_order"
_RESULT_TABLE = "flow_step_results"
_RESULT_COLUMNS = ("flow_run_id", "step_order")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            _ATTEMPT_INDEX,
            _ATTEMPT_TABLE,
            _ATTEMPT_COLUMNS,
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            _RESULT_INDEX,
            _RESULT_TABLE,
            _RESULT_COLUMNS,
            unique=False,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _RESULT_INDEX,
            table_name=_RESULT_TABLE,
            postgresql_concurrently=True,
        )
        op.drop_index(
            _ATTEMPT_INDEX,
            table_name=_ATTEMPT_TABLE,
            postgresql_concurrently=True,
        )
