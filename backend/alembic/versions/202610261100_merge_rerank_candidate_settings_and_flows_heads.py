"""Merge develop's rerank candidate settings head and the flow head.

Develop's 202610221000 (rerank candidate settings) follows 202610161000, which
the flow chain already contains through 202610231000, so a flow database runs
it here and a develop database picks up the flow chain.

The flow chain's own "flows on by default" revision had the same id,
202610221000, and became 202610220930. Develop keeps its id because develop
databases record it; a flow database is past that revision, and alembic
stores only heads, so the renumbering leaves it unaffected. A database stamped
at the old id with the branch's schema is refused with its repair
(eneo.database.renumbered_revisions).

The flow chain's jobs poll index (202610261000) once sat between 202610251100
and this merge. Develop shipped the same index as 202611030830, so the branch's
copy was dropped: a flow database already has the index, and 202611030830
keeps it (CREATE INDEX CONCURRENTLY IF NOT EXISTS).

Revision ID: 202610261100
Revises: 202610221000, 202610251100
Create Date: 2026-10-26 11:00:00.000000
"""

revision: str = "202610261100"
down_revision: tuple[str, str] = ("202610221000", "202610251100")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
