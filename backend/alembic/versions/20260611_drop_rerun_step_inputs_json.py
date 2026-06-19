"""drop duplicate Flow rerun step input JSONB

Revision ID: 20260611_drop_rerun_step_inputs
Revises: 20260611_flow_class_retention
Create Date: 2026-06-11 21:35:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260611_drop_rerun_step_inputs"
down_revision = "20260611_flow_class_retention"
branch_labels = None
depends_on = None

_RERUN_OPERATIONS_TABLE = "flow_run_rerun_operations"
_COLUMN_NAME = "step_inputs_json"


def upgrade() -> None:
    op.drop_column(_RERUN_OPERATIONS_TABLE, _COLUMN_NAME)


def downgrade() -> None:
    # Downgrade only restores the nullable column shape. The canonical history
    # now lives in flow_run_step_input_files plus root_step_input_override_requested.
    op.add_column(
        _RERUN_OPERATIONS_TABLE,
        sa.Column(_COLUMN_NAME, postgresql.JSONB(), nullable=True),
    )
