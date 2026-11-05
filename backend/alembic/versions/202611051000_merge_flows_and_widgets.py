"""Join the Flows and widget histories

Revision ID: 202611051000
Revises: 202611031100, 202611031206
"""

from collections.abc import Sequence

revision: str = "202611051000"
down_revision: tuple[str, str] = ("202611031100", "202611031206")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
