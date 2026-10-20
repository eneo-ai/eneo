"""merge widget and develop migration heads

Revision ID: 202610201500
Revises: 202610131000, 202610191000
Create Date: 2026-10-20 15:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202610201500"
down_revision: tuple[str, str] = ("202610131000", "202610191000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
