"""Join conversation settings with the current develop migrations.

Revision ID: 202610281000
Revises: 202610191100, 202610261300
"""

from collections.abc import Sequence

revision: str = "202610281000"
down_revision: tuple[str, str] = ("202610191100", "202610261300")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
