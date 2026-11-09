"""record the admin's acknowledgement of a widget's external MCP tools

Activating a widget whose assistant reaches MCP servers outside Eneo now
needs the tenant admin to acknowledge that anonymous visitors can make the
assistant call their tools. The acknowledgement is stored on the widget with
the server ids it was given for, so a later change to the assistant's
servers shows up as unacknowledged.

Revision ID: 202611091200
Revises: 202611091110
Create Date: 2026-11-09 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202611091200"
down_revision: str | None = "202611091110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column("external_tools_acknowledgement", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("widgets", "external_tools_acknowledgement")
