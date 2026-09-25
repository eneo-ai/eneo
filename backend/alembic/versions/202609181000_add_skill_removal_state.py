"""Retain removed Skills and their immutable revisions (moved to 202609231000).

The schema change lives in 202609231000 so release/v2.2 can ship it on its own
head. This revision keeps its place in the develop chain as a no-op, so a v2.2
database that already has the schema never applies it twice.

Revision ID: 202609181000
Revises: 202609161000
"""

revision = "202609181000"
down_revision = "202609161000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
