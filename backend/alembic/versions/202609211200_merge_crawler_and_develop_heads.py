"""merge crawler and develop migration heads

Revision ID: 202609211200
Revises: 202609101000, 202609101130
Create Date: 2026-09-21 12:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202609211200"
down_revision: tuple[str, str] = ("202609101000", "202609101130")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
