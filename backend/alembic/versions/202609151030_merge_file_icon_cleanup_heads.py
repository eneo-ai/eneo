"""merge develop's file/icon cleanup tracking with the tidy AI Builder chain

Revision ID: 202609151030
Revises: 202609131200, 202609101000
Create Date: 2026-09-15 10:30:00.000000

Develop's chain (202609081400 file/icon legacy cleanup tracking, 202608271000
user credential version, 202609101000 tenant API key origin policy) and the
tidy AI Builder chain's 202609131200 both descend from 202609111000. This
revision joins the two heads; it carries no schema change of its own.
"""

from collections.abc import Sequence

revision: str = "202609151030"
down_revision: str | Sequence[str] | None = ("202609131200", "202609101000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
