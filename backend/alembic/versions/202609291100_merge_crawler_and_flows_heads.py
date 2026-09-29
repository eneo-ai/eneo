"""merge crawler and flows migration heads

Revision ID: 202609291100
Revises: 202609281000, 202609291000
Create Date: 2026-09-29 11:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202609291100"
down_revision: tuple[str, str] = ("202609281000", "202609291000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
