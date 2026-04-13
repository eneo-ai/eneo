"""drop legacy completion_models.token_limit column

Revision ID: 20260413_drop_cm_token_limit
Revises: 20260412_flow_exec_timing
Create Date: 2026-04-13 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260413_drop_cm_token_limit"
down_revision = "20260412_flow_exec_timing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {
        column["name"] for column in inspector.get_columns("completion_models")
    }

    if "token_limit" in existing_columns:
        op.drop_column("completion_models", "token_limit")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = {
        column["name"] for column in inspector.get_columns("completion_models")
    }

    if "token_limit" not in existing_columns:
        op.add_column(
            "completion_models",
            sa.Column("token_limit", sa.Integer(), nullable=True),
        )
        conn.execute(
            sa.text("UPDATE completion_models SET token_limit = max_input_tokens")
        )
        op.alter_column("completion_models", "token_limit", nullable=False)
