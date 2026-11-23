"""Join the Flows head and the file origin revision

Revision ID: 202611231020
Revises: 202611230556, 202611181900
"""

from collections.abc import Sequence

revision: str = "202611231020"
down_revision: tuple[str, str] = ("202611230556", "202611181900")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
