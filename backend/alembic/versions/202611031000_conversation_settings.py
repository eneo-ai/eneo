"""Persist choices with their conversation.

Nullable, without a default or backfill: old sessions initialize on first use.
The catalog change fails immediately if chat holds the table lock; rerun the
migration when the short lock is available. No table scan or rewrite is needed.

Revision ID: 202611031000
Revises: 202611030830
"""

from alembic import op

revision = "202611031000"
down_revision = "202611030830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("ALTER TABLE sessions ADD COLUMN settings JSONB")


def downgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("ALTER TABLE sessions DROP COLUMN settings")
