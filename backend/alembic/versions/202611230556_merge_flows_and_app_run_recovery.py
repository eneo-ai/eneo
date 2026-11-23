"""Join develop's app run recovery indexes and the Flows head

Revision ID: 202611230556
Revises: 202611111000, 202611190900
"""

from collections.abc import Sequence

revision: str = "202611230556"
down_revision: tuple[str, str] = ("202611111000", "202611190900")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
