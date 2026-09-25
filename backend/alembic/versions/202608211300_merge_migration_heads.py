"""merge migration heads

Revision ID: 202608211300
Revises: 202608041200, 202608181000
Create Date: 2026-08-21 13:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202608211300"
down_revision: tuple[str, str] = ("202608041200", "202608181000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
