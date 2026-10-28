"""Join conversation settings and editable document versions.

Revision ID: 202610191100
Revises: 202610191001, 202610161200
"""

from collections.abc import Sequence

revision: str = "202610191100"
down_revision: tuple[str, str] = ("202610191001", "202610161200")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
