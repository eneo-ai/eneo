"""add active_request_id to builder sessions

Revision ID: 20260415_builder_active_request
Revises: 20260414_builder_files
Create Date: 2026-04-15 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260415_builder_active_request"
down_revision = "20260414_builder_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "builder_sessions",
        sa.Column("active_request_id", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("builder_sessions", "active_request_id")
