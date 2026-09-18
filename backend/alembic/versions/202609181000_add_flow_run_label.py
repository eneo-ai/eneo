"""Add an optional caller-supplied flow run label.

Revision ID: 202609181000
Revises: 202609171100
"""

import sqlalchemy as sa

from alembic import op

revision = "202609181000"
down_revision = "202609171100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("flow_runs", sa.Column("run_label", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_flow_runs_run_label_length",
        "flow_runs",
        "char_length(run_label) BETWEEN 1 AND 120",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("ck_flow_runs_run_label_length", "flow_runs", type_="check")
    op.drop_column("flow_runs", "run_label")
