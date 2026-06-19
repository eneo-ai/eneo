"""allow Flow input file projections across run attempts

Rerun root file inputs are projected before their next attempt row exists, so
valid projections can target attempt numbers greater than one.

Revision ID: 20260607_step_input_attempt
Revises: 20260605_webhook_attempt_fk
Create Date: 2026-06-07 15:45:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "20260607_step_input_attempt"
down_revision = "20260605_webhook_attempt_fk"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "ck_flow_run_step_input_files_attempt_no_positive"
_STEP_INPUT_FILES_TABLE = "flow_run_step_input_files"


def upgrade() -> None:
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        _STEP_INPUT_FILES_TABLE,
        "attempt_no >= 1",
        postgresql_not_valid=True,
    )
    op.execute(
        f"ALTER TABLE {_STEP_INPUT_FILES_TABLE} VALIDATE CONSTRAINT {_CONSTRAINT_NAME}"
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, _STEP_INPUT_FILES_TABLE, type_="check")
