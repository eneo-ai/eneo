"""Persist choices with their conversation.

Nullable, without a default or backfill: old sessions initialize on first use.
The catalog change fails immediately if chat holds the table lock; rerun the
complete Alembic upgrade command when the short lock is available. No table
scan or rewrite is needed.

An ordinary upgrade from develop runs this migration once. A database that
already ran it on a feature branch has the column and may be missing develop
revisions. Back up first and identify the checkout and last develop revision
actually applied. Do not infer that revision from the settings revision alone.

For databases at 202611051000, its former parents were 202611031206 and
202610071400. Use the matching former parent as BASE below. Always run the
first stamp with the original checkout of 202611051000, then switch to this
checkout. Stamping changes only version tracking; the saved column and values
stay in place.

    alembic stamp BASE
    alembic upgrade 202611190900

Before the second stamp, verify the existing column in PostgreSQL's catalog:

    SELECT data_type, is_nullable, column_default FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sessions'
      AND column_name = 'settings';

Proceed only if the single row is (jsonb, YES, NULL). Otherwise reconcile the
actual schema on a database copy first. Once verified:

    alembic stamp 202611201000
    alembic upgrade head

For an earlier experimental checkout, verify its actual migration history and
schema on a database copy before selecting a recovery path.

Revision ID: 202611201000
Revises: 202611190900
"""

from alembic import op

revision = "202611201000"
down_revision = "202611190900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("ALTER TABLE sessions ADD COLUMN settings JSONB")


def downgrade() -> None:
    op.execute("LOCK TABLE sessions IN ACCESS EXCLUSIVE MODE NOWAIT")
    op.execute("ALTER TABLE sessions DROP COLUMN settings")
