"""add mcp tool ui resource pin

Revision ID: 202610011100
Revises: 202608191105
Create Date: 2026-10-01 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610011100"
down_revision: str | None = "202608191105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The SHA-256 of the MCP App view HTML an administrator approved for the
    # tool. It follows the approval lifecycle of the definition: sync writes
    # the pending hash, approval promotes it. Only the stored view with the
    # approved hash is ever served.
    op.add_column(
        "mcp_server_tools",
        sa.Column("ui_resource_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "mcp_server_tools",
        sa.Column("pending_ui_resource_sha256", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_tools", "pending_ui_resource_sha256")
    op.drop_column("mcp_server_tools", "ui_resource_sha256")
