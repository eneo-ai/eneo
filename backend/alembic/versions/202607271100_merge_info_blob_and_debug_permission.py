"""merge InfoBlob versions and assistant debug permission heads

Revision ID: 202607271100
Revises: 202607271000, 202607261730
"""

from collections.abc import Sequence

revision: str = "202607271100"
down_revision: str | tuple[str, str] | None = ("202607271000", "202607261730")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
