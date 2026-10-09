"""merge the widget and develop migration heads

Revision ID: 202610091000
Revises: 202609231701, 202610011100
Create Date: 2026-10-09 10:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202610091000"
down_revision: tuple[str, str] = ("202609231701", "202610011100")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
