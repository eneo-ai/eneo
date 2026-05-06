"""sessions: nullable user_id + add api_key_id

Service API keys resolve to a synthetic UserInDB whose id is never inserted
into ``users``. Writing that synthetic id into ``sessions.user_id`` (NOT NULL
FK to ``users.id``) blew up /ask with a ForeignKeyViolationError, surfacing
as a 500 on every question asked through a pk_ service key.

This migration:
1. Drops NOT NULL on ``sessions.user_id`` so service-key sessions can omit it.
2. Adds ``sessions.api_key_id`` (FK to ``api_keys_v2.id``, ON DELETE SET NULL)
   so service-key sessions still have an owning principal recorded for
   ownership checks and audit.
3. Indexes ``api_key_id`` for the ownership-check query path.

Revision ID: 202605061100
Revises: 202604291030
Create Date: 2026-05-06
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202605061100"
down_revision = "202604291030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sessions",
        "user_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=True,
    )
    op.add_column(
        "sessions",
        sa.Column(
            "api_key_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("api_keys_v2.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sessions_api_key_id",
        "sessions",
        ["api_key_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_api_key_id", table_name="sessions")
    op.drop_column("sessions", "api_key_id")
    # Fail-fast: if service-key sessions exist, the operator must purge them
    # before reverting; we don't synthesize fake user rows on rollback.
    op.execute(
        "ALTER TABLE sessions ALTER COLUMN user_id SET NOT NULL"
    )
