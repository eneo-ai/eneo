"""join widget and browser-session histories

Revision ID: 202611031000
Revises: 202610291001, 202611021100
"""

from collections.abc import Sequence

revision: str = "202611031000"
down_revision: tuple[str, str] = ("202610291001", "202611021100")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
