"""Merge the develop and Flow migration histories.

Revision ID: 202607311200
Revises: 202607301200, 202607291800_attempt_admit_idx
Create Date: 2026-07-31 12:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202607311200"
down_revision: tuple[str, str] = (
    "202607301200",
    "202607291800_attempt_admit_idx",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
