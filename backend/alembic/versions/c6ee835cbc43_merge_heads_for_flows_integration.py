"""Merge divergent Alembic heads so `upgrade head` has a single target.

Revision ID: c6ee835cbc43
Revises: 1d7f1a43c0c2, 9d2a6c01f3e7
Create Date: 2026-03-04 17:34:24.756666
"""


# revision identifiers, used by Alembic.
revision = "c6ee835cbc43"
down_revision = ("1d7f1a43c0c2", "9d2a6c01f3e7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op merge migration."""
    pass


def downgrade() -> None:
    """No-op merge migration."""
    pass
