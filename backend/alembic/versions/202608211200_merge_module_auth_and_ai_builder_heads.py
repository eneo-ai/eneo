"""merge module auth client config and flow ai builder schema heads

Revision ID: 202608211200
Revises: 202608041200, 202608201200
Create Date: 2026-08-21 12:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202608211200"
down_revision: tuple[str, str] = ("202608041200", "202608201200")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
