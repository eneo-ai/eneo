"""create prompt_library table

Admin-managed prompt templates shared across personal assistants
(personal-assistant governance, Phase 1).

Held deliberately separate from ``prompts`` because that table follows an
immutable-history pattern (each update inserts a new row). Mixing both
lifecycles in the same table would corrupt audit / insights flows.

Revision ID: 202605211500
Revises: 20260501_backfill_model_costs
Create Date: 2026-05-21
"""

import sqlalchemy as sa

from alembic import op

revision = "202605211500"
down_revision = "20260501_backfill_model_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_library",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_prompt_library_tenant_name"),
    )
    op.create_index(
        "ix_prompt_library_tenant_id",
        "prompt_library",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_prompt_library_tenant_id", table_name="prompt_library")
    op.drop_table("prompt_library")
