"""add mcp tool meta

Revision ID: 202608191100
Revises: 202610081100
Create Date: 2026-08-19 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202608191100"
down_revision: str | None = "202610081100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tool-level MCP `_meta` (e.g. the MCP Apps ui declaration). Follows the
    # same approval lifecycle as description/input_schema: discovery writes
    # pending_meta, admin approval promotes it to meta.
    op.add_column(
        "mcp_server_tools",
        sa.Column("meta", JSONB(), nullable=True),
    )
    op.add_column(
        "mcp_server_tools",
        sa.Column("pending_meta", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_tools", "pending_meta")
    op.drop_column("mcp_server_tools", "meta")
