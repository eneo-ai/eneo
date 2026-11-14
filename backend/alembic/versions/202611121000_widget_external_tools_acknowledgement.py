"""record the admin's acknowledgement of a widget's external MCP tools

A widget's visitor turns reach tools on MCP servers outside Eneo only once a
tenant admin has acknowledged that anonymous visitors can make the assistant
call them. The acknowledgement is stored on the widget with the servers and
tools it was given for; a tool switched on later stays out of visitor turns
until an admin acknowledges it too.

Revision ID: 202611121000
Revises: 202611091200
Create Date: 2026-11-12 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202611121000"
down_revision: str | None = "202611091200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column("external_tools_acknowledgement", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("widgets", "external_tools_acknowledgement")
