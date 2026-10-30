"""merge develop capability providers with the flows branch

Revision ID: 202609081000
Revises: 202609052200, 202609071000
Create Date: 2026-09-08 10:55:00.000000

Joins the develop line (capability MCP providers, file icon migration pause)
with the flows line (transcript corrections, evidence classification level,
review permission grant). No schema change of its own.
"""

from collections.abc import Sequence

revision: str = "202609081000"
down_revision: str | Sequence[str] | None = ("202609052200", "202609071000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
