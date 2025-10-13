"""add website crawl scheduling

Revision ID: add_website_crawl_scheduling
Revises: 2f8e9a1b3c5d
Create Date: 2025-10-13 09:00:00.000000

Why: Add crawl scheduling improvements for websites:
1. last_crawled_at column - Separates crawl timing from record update timing
   This prevents crawl schedule reset when editing website settings
2. Scheduling index - Optimizes queries for finding websites that need crawling
   Improves performance as the number of websites scales

Note: This migration consolidates previously scattered crawl scheduling features
into one clean migration, skipping the temporary crawl4ai experiment.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_website_crawl_scheduling'
down_revision = '2f8e9a1b3c5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add last_crawled_at column and scheduling index to websites table.

    Why:
    - last_crawled_at: Tracks when website was last crawled independently of record updates
    - Scheduling index: Optimizes queries for scheduled crawl job processing
    """
    # 1. Add last_crawled_at column (nullable)
    op.add_column(
        'websites',
        sa.Column('last_crawled_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )

    # 2. Backfill existing websites: set last_crawled_at = updated_at for websites
    # that have at least one crawl run, NULL for never-crawled websites
    op.execute("""
        UPDATE websites w
        SET last_crawled_at = w.updated_at
        WHERE EXISTS (
            SELECT 1 FROM crawl_runs cr
            WHERE cr.website_id = w.id
        )
    """)

    # 3. Add database index for efficient crawl scheduling queries
    # This optimizes: "find websites that need crawling based on update_interval"
    op.create_index(
        'idx_websites_crawl_scheduling',
        'websites',
        ['update_interval', 'updated_at']
    )


def downgrade() -> None:
    """Remove crawl scheduling enhancements."""
    # Remove index first (dependencies)
    op.drop_index('idx_websites_crawl_scheduling', table_name='websites')

    # Remove column
    op.drop_column('websites', 'last_crawled_at')
