"""Join the v2.2 Skill removal branch with the develop chain.

A v2.2 database stamped at 202609231000 still runs 202609171000 through
202609181000 here; a develop database stamped at 202609181000 runs
202609231000, which finds its schema present and skips.

Revision ID: 202609231001
Revises: 202609181000, 202609231000
"""

revision = "202609231001"
down_revision = ("202609181000", "202609231000")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
