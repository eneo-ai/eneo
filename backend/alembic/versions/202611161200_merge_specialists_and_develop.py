"""Merge assistant specialists with develop's retention and identity revisions.

Keep both existing migration histories intact. Upgrading from either branch
applies the other branch's revisions before joining them here, without dropping
specialists or stamping unapplied migrations as complete.

Revision ID: 202611161200
Revises: 202610201100, 202611091200
"""

revision: str = "202611161200"
down_revision: tuple[str, str] = ("202610201100", "202611091200")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
