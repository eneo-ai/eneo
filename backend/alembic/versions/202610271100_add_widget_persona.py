"""add widget persona

The voice a widget answers with: a name and an uploaded avatar shown inside
the conversation, and whether that avatar is the launcher button. One JSONB
document per widget and per template, like texts and theme; a template's
published release carries its own copy inside ``published``, where a missing
key reads as the neutral persona.

Revision ID: 202610271100
Revises: 202610271000
Create Date: 2026-10-27 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202610271100"
down_revision: str | None = "202610271000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("widgets", "widget_templates"):
        op.add_column(
            table,
            sa.Column(
                "persona",
                JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    for table in ("widget_templates", "widgets"):
        op.drop_column(table, "persona")
