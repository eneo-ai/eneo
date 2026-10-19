"""Merge conversation settings with the current develop migration head.

Revision ID: 202610071000
Revises: 202609251000, 202610051000
"""

from collections.abc import Sequence

revision: str = "202610071000"
down_revision: tuple[str, str] = ("202609251000", "202610051000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
