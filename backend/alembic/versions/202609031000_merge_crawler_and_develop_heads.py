"""merge crawler and develop migration heads

Revision ID: 202609031000
Revises: 202608281200, 202608311430
Create Date: 2026-09-03 10:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202609031000"
down_revision: tuple[str, str] = ("202608281200", "202608311430")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
