"""merge crawler and develop migration heads

Revision ID: 202609291000
Revises: 202609212000, 202609231001
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202609291000"
down_revision: tuple[str, str] = ("202609212000", "202609231001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
