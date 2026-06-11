"""add users.is_system_user

Adds a boolean marker that protects per-tenant system users from ordinary
deletion, search, and cleanup paths. The Prompt Guide helper and any future
help assistants are owned by this system user; without the marker we cannot
distinguish those rows from real human users.

Repo guards (deletion blocks, cleanup-job filters, tenant query exclusions)
land in a later step. This migration is schema-only: the column plus a
partial index that keeps the small "system users" set cheap to look up.

Revision ID: 202605211000
Revises: 20260501_backfill_model_costs
Create Date: 2026-05-21
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202605211000"
down_revision = "20260501_backfill_model_costs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_system_user",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_users_system_user",
        "users",
        ["is_system_user"],
        unique=False,
        postgresql_where=sa.text("is_system_user = true"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_users_system_user",
        table_name="users",
        postgresql_where=sa.text("is_system_user = true"),
    )
    op.drop_column("users", "is_system_user")
