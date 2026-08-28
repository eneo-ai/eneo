"""merge tidy AI Builder and develop migration heads

Revision ID: 202608281300
Revises: 202608251330, 202608281200
Create Date: 2026-08-28 13:00:00.000000
"""

from collections.abc import Sequence

revision: str = "202608281300"
down_revision: tuple[str, str] = ("202608251330", "202608281200")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
