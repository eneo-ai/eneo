"""separate Flow rerun input override control from audit JSON

Revision ID: 20260608_rerun_input_flag
Revises: 20260608_result_file_no_default
Create Date: 2026-06-08 03:35:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260608_rerun_input_flag"
down_revision = "20260608_result_file_no_default"
branch_labels = None
depends_on = None

_RERUN_OPERATIONS_TABLE = "flow_run_rerun_operations"
_COLUMN_NAME = "root_step_input_override_requested"


def upgrade() -> None:
    op.add_column(
        _RERUN_OPERATIONS_TABLE,
        sa.Column(
            _COLUMN_NAME,
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {_RERUN_OPERATIONS_TABLE}
            SET {_COLUMN_NAME} = TRUE
            WHERE step_inputs_json IS NOT NULL
            """
        )
    )
    op.alter_column(
        _RERUN_OPERATIONS_TABLE,
        _COLUMN_NAME,
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column(_RERUN_OPERATIONS_TABLE, _COLUMN_NAME)
