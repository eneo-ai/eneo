"""merge widget and develop icon-reference migration heads

Revision ID: 202610271000
Revises: 202610261000, 202610261300
Create Date: 2026-10-27 20:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202610271000"
down_revision: tuple[str, str] = ("202610261000", "202610261300")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
