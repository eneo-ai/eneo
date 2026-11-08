"""Persist choices with their conversation.

Nullable, without a default or backfill: old sessions initialize on first use.
The catalog change fails immediately if chat holds the table lock; rerun the
migration when the short lock is available. No table scan or rewrite is needed.

This revision first followed 202611031206, where 202610071400 now sits. A
database migrated on that chain reports itself at head, so `alembic upgrade
head` would skip 202610071400. To bring it up with this code and keep the
saved settings:

    alembic stamp 202611031206
    alembic upgrade 202610071400
    alembic stamp 202611051000
    alembic upgrade head

Revision ID: 202611051000
Revises: 202610071400
"""

from alembic import op

revision = "202611051000"
down_revision = "202610071400"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("ALTER TABLE sessions ADD COLUMN settings JSONB")


def downgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("ALTER TABLE sessions DROP COLUMN settings")
