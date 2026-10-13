"""Per-source policy for spreadsheet files synced from an integration.

Tabular files are now kept as originals so the table analysis tools can open
them. A source chooses whether such files are also chunked and embedded for
search (the default, today's behaviour) or kept for the tools only.

Revision ID: 202610131200
Revises: 202610131800
Create Date: 2026-10-13 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610131200"
down_revision: str | None = "202610131800"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "integration_knowledge"
_COLUMN = "tabular_policy"
_CONSTRAINT = "ck_integration_knowledge_tabular_policy"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Text(), nullable=False, server_default="index_and_tool"),
    )
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        f"{_COLUMN} IN ('index_and_tool', 'tool_only')",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.drop_column(_TABLE, _COLUMN)
