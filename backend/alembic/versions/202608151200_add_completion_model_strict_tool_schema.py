"""Add the strict tool schema capability to completion models.

Records, per completion model, whether its provider route honors strict tool
schemas natively. Absent evidence means unsupported, so nothing is backfilled:
a model is marked only after someone measures it. Downgrading discards those
declarations and every model returns to permissive tool schemas, which is the
same safe state a fresh upgrade starts from; re-upgrading therefore requires
declaring the measured models again.

Revision ID: 202608151200
Revises: 202608111400
Create Date: 2026-08-15 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "202608151200"
down_revision = "202608111400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "completion_models",
        sa.Column(
            "supports_strict_tool_schema",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("completion_models", "supports_strict_tool_schema")
