"""merge context usage and restart-safe knowledge job heads

Revision ID: 202607301100
Revises: 202607291000, 202607301000
Create Date: 2026-07-30 11:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202607301100"
down_revision: tuple[str, str] = ("202607291000", "202607301000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
