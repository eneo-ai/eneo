"""merge the develop join with the tidy chain's runtime upload audio seconds

Revision ID: 202609281000
Revises: 202609271000, 202609271200
Create Date: 2026-09-28 10:00:00.000000

202609271000 joined develop's chain with the tidy AI Builder chain at
202609241200. The tidy chain has since added 202609271200 on 202609241200.
This revision joins the two; it carries no schema change of its own.
"""

from collections.abc import Sequence

revision: str = "202609281000"
down_revision: str | Sequence[str] | None = ("202609271000", "202609271200")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
