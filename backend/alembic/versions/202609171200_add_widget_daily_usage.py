"""add widget daily usage

Revision ID: 202609171200
Revises: 202609171100
Create Date: 2026-09-17 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609171200"
down_revision: str | None = "202609171100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "widget_daily_usage",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("widget_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("questions", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_budget", sa.Integer(), server_default="0", nullable=False),
        sa.Column("blocked_rate", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["widget_id"], ["widgets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "widget_id", "day", name="uq_widget_daily_usage_widget_day"
        ),
    )


def downgrade() -> None:
    op.drop_table("widget_daily_usage")
