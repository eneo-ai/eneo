"""Merge the latest develop and Flow migration heads.

Revision ID: 202608181700
Revises: 202608121500, 202608161930_call_transcription
Create Date: 2026-08-18 17:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202608181700"
down_revision: tuple[str, str] = (
    "202608121500",
    "202608161930_call_transcription",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
