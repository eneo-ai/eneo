"""merge develop's whats-new, widget and Skill removal chain with the tidy AI Builder chain

Revision ID: 202609271000
Revises: 202609241200, 202609231001
Create Date: 2026-09-27 10:00:00.000000

Both chains descend from 202609101000. Develop's (202609171000 legacy widgets
drop, 202609151000 what's new state, 202609161000 its feature flag seed,
202609181000 and 202609231000 Skill removal, joined at 202609231001) and the
tidy AI Builder chain ending at 202609241200 meet here. The tidy chain's
202609151040, 202609161010 and 202609181010 were renumbered from ids develop
had already taken. This revision carries no schema change of its own.
"""

from collections.abc import Sequence

revision: str = "202609271000"
down_revision: str | Sequence[str] | None = ("202609241200", "202609231001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
