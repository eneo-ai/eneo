"""Join the develop and Flows histories

Revision ID: 202611111000
Revises: 202611091200, 202611101200
"""

from collections.abc import Sequence

revision: str = "202611111000"
down_revision: tuple[str, str] = ("202611091200", "202611101200")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
