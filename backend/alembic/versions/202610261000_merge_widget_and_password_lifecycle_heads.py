"""merge widget and password lifecycle migration heads

Revision ID: 202610261000
Revises: 202610201500, 202610161000
Create Date: 2026-10-26 10:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202610261000"
down_revision: tuple[str, str] = ("202610201500", "202610161000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
