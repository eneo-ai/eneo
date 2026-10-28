"""Join conversation settings with the latest develop migration head.

Revision ID: 202610191001
Revises: 202610071000, 202610141000
"""

from collections.abc import Sequence

revision: str = "202610191001"
down_revision: tuple[str, str] = ("202610071000", "202610141000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
