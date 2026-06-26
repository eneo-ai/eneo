"""add Flow step-result error codes

Revision ID: 20260612_step_result_err_code
Revises: 20260611_flow_class_retention
Create Date: 2026-06-12 13:55:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260612_step_result_err_code"
down_revision = "20260611_flow_class_retention"
branch_labels = None
depends_on = None

_STEP_RESULTS_TABLE = "flow_step_results"
_COLUMN_NAME = "error_code"


def upgrade() -> None:
    op.add_column(
        _STEP_RESULTS_TABLE, sa.Column(_COLUMN_NAME, sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column(_STEP_RESULTS_TABLE, _COLUMN_NAME)
