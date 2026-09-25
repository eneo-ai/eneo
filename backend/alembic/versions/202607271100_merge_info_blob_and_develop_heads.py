"""merge InfoBlob versions with the current develop migration head

Revision ID: 202607271100
Revises: 202607271000, 202607271416
"""

from collections.abc import Sequence

revision: str = "202607271100"
down_revision: str | tuple[str, str] | None = ("202607271000", "202607271416")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
