"""drop legacy widgets table

Revision ID: 202609171000
Revises: 202608271000
Create Date: 2026-09-17 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609171000"
down_revision: str | None = "202609101000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The 2024 widget feature lost its routers and its api_keys binding
    # in 2024; nothing reads this table any more. The upcoming embeddable
    # widget feature gets a new table with different ownership semantics.
    op.drop_table("widgets")


def downgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("bot_introduction", sa.String(), nullable=False),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("size", sa.String(), nullable=False),
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
        sa.Column("assistant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assistant_id"],
            ["assistants.id"],
            name="widgets_assistants_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="widgets_users_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="widgets_pkey"),
    )
