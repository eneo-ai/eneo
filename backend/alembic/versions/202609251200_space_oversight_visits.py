"""keep oversight visits for members to see

`space_oversight_visits` records each time a tenant administrator joined a
space through oversight, with role and reason, and when that membership
ended. The join marker lives on the administrator's `spaces_users` row and
goes with it on leave; these rows stay, so members still see the visit
afterwards. A visit is deleted with its space and keeps no person once the
user is deleted.

The table is new and empty. Its foreign keys lock `tenants`, `spaces` and
`users` briefly, so the revision gives up rather than queue behind a long
transaction.

Revision ID: 202609251200
Revises: 202609251100
Create Date: 2026-09-25 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609251200"
down_revision: str | None = "202609251100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "space_oversight_visits"


def upgrade() -> None:
    # Rerunning the upgrade is safe after a timeout: nothing committed.
    op.execute("SET LOCAL lock_timeout = '5s'")

    op.create_table(
        TABLE,
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("space_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("left_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="space_oversight_visits_pkey"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="space_oversight_visits_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["spaces.id"],
            name="space_oversight_visits_space_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="space_oversight_visits_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 10 AND 500",
            name="ck_space_oversight_visits_reason_length",
        ),
        sa.CheckConstraint(
            "left_at IS NULL OR left_at >= joined_at",
            name="ck_space_oversight_visits_left_after_joined",
        ),
    )
    op.create_index(
        "ix_space_oversight_visits_space_id_joined_at",
        TABLE,
        ["space_id", "joined_at"],
    )
    op.create_index(
        "uq_space_oversight_visits_open",
        TABLE,
        ["space_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("left_at IS NULL"),
    )

    # Later revisions in the same run must not inherit the short timeout.
    op.execute("SET LOCAL lock_timeout = DEFAULT")


def downgrade() -> None:
    # Dropping the table drops its indexes and constraints with it.
    op.drop_table(TABLE)
