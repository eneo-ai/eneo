"""Merge the develop and Flow migration histories.

Revision ID: 202608111400
Revises: 202607311200, 202608101300
Create Date: 2026-08-11 14:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202608111400"
down_revision: tuple[str, str] = ("202607311200", "202608101300")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
