"""require explicit Flow step-input projection attempts

Revision ID: 20260608_step_input_no_default
Revises: 20260607_flow_runtime_uploads
Create Date: 2026-06-08 02:45:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260608_step_input_no_default"
down_revision = "20260607_flow_runtime_uploads"
branch_labels = None
depends_on = None

_STEP_INPUT_FILES_TABLE = "flow_run_step_input_files"


def upgrade() -> None:
    op.alter_column(
        _STEP_INPUT_FILES_TABLE,
        "attempt_no",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=None,
    )


def downgrade() -> None:
    op.alter_column(
        _STEP_INPUT_FILES_TABLE,
        "attempt_no",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("1"),
    )
