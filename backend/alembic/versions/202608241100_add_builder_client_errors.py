"""add builder client errors

Revision ID: 202608241100
Revises: 202608211200
Create Date: 2026-08-24 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608241100"
down_revision: str | None = "202608211200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "builder_client_errors",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("client_event_id", sa.UUID(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["session_id", "tenant_id"],
            ["builder_sessions.id", "builder_sessions.tenant_id"],
            ondelete="CASCADE",
            name="fk_builder_client_errors_session_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "client_event_id",
            name="uq_builder_client_errors_tenant_event",
        ),
    )
    op.create_index(
        "ix_builder_client_errors_session_id", "builder_client_errors", ["session_id"]
    )
    op.create_index(
        "ix_builder_client_errors_created_at", "builder_client_errors", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("builder_client_errors")
