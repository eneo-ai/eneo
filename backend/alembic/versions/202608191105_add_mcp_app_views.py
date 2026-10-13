"""add mcp app views

Revision ID: 202608191105
Revises: 202608191100
Create Date: 2026-08-19 11:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "202608191105"
down_revision: str | None = "202608191100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Content-addressed cache of MCP App view HTML fetched via resources/read.
    # A changed template creates a new row; old rows keep serving messages
    # rendered against them.
    op.create_table(
        "mcp_app_views",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mcp_server_id",
            UUID(as_uuid=True),
            sa.ForeignKey("mcp_servers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("ui_meta", JSONB(), nullable=True),
        sa.Column("fetched_at", sa.TIMESTAMP(timezone=True), nullable=False),
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
        sa.UniqueConstraint(
            "mcp_server_id",
            "uri",
            "content_hash",
            name="uq_mcp_app_views_server_uri_hash",
        ),
    )
    op.create_index("ix_mcp_app_views_tenant_id", "mcp_app_views", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_app_views_tenant_id", table_name="mcp_app_views")
    op.drop_table("mcp_app_views")
