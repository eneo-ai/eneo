"""add builder session file associations

Revision ID: 20260414_builder_files
Revises: 20260412_flow_exec_timing
Create Date: 2026-04-14 00:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260414_builder_files"
down_revision = "20260412_flow_exec_timing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "builder_session_files",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("session_id", "file_id"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["builder_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_builder_session_files_tenant_id",
        "builder_session_files",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_builder_session_files_tenant_id", table_name="builder_session_files")
    op.drop_table("builder_session_files")
