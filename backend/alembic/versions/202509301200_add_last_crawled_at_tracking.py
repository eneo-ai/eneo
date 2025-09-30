"""add last_crawled_at column for accurate crawl interval tracking

Revision ID: add_last_crawled_at
Revises: enhance_update_intervals
Create Date: 2025-09-30 12:00:00.000000

Why: Fixes crawl scheduling bug where editing website settings would reset
the crawl schedule. Uses dedicated last_crawled_at timestamp instead of
updated_at to track when websites were last crawled.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_last_crawled_at'
down_revision = 'enhance_update_intervals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add last_crawled_at column to websites table.

    Why: Separates crawl timing from record update timing. Prevents settings
    changes from interfering with crawl schedules.
    """
    # Add nullable column
    op.add_column(
        'websites',
        sa.Column('last_crawled_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )

    # Backfill existing websites: set last_crawled_at = updated_at for websites
    # that have at least one crawl run, NULL for never-crawled websites
    op.execute("""
        UPDATE websites w
        SET last_crawled_at = w.updated_at
        WHERE EXISTS (
            SELECT 1 FROM crawl_runs cr
            WHERE cr.website_id = w.id
        )
    """)


def downgrade() -> None:
    """Remove last_crawled_at column.

    Why: Rollback to using updated_at for scheduling (previous behavior).
    """
    op.drop_column('websites', 'last_crawled_at')