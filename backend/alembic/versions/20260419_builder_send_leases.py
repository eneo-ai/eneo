"""add lease fields to builder sessions

Revision ID: 20260419_builder_send_leases
Revises: 20260415_builder_active_request
Create Date: 2026-04-19 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260419_builder_send_leases"
down_revision = "20260415_builder_active_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "builder_sessions",
        sa.Column("lock_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "builder_sessions",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "builder_sessions",
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE builder_sessions "
            "SET active_request_id = NULL "
            "WHERE active_request_id IS NOT NULL AND lock_expires_at IS NULL"
        )
    )
    op.create_index(
        "ix_builder_sessions_lock_expires_at",
        "builder_sessions",
        ["lock_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_builder_sessions_lock_expires_at", table_name="builder_sessions")
    op.drop_column("builder_sessions", "lock_expires_at")
    op.drop_column("builder_sessions", "locked_at")
    op.drop_column("builder_sessions", "lock_token")
