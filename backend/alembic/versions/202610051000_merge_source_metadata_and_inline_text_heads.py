"""merge source_metadata and inline text migration heads

Revision ID: 202610051000
Revises: 202609221000, 202610011000
Create Date: 2026-10-05 10:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202610051000"
down_revision: tuple[str, str] = ("202609221000", "202610011000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
