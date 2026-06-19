"""require explicit Flow step-result file attempts

Revision ID: 20260608_result_file_no_default
Revises: 20260608_step_input_no_default
Create Date: 2026-06-08 03:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260608_result_file_no_default"
down_revision = "20260608_step_input_no_default"
branch_labels = None
depends_on = None

_STEP_RESULT_FILES_TABLE = "flow_run_step_result_files"


def upgrade() -> None:
    op.alter_column(
        _STEP_RESULT_FILES_TABLE,
        "attempt_no",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.alter_column(
        _STEP_RESULT_FILES_TABLE,
        "attempt_no",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("1"),
    )
