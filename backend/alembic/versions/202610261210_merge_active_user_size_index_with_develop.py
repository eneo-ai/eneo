"""merge the 2.3 active user size index with the develop migration head

202610261200 shipped in a 2.3 patch on top of 202610191000. Databases on that
patch, and databases already on the develop head, both reach this revision.

Revision ID: 202610261210
Revises: 202610261200, 202610221000
"""

from collections.abc import Sequence

revision: str = "202610261210"
down_revision: str | tuple[str, str] | None = ("202610261200", "202610221000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
