"""add crawl scheduling enhancements

Revision ID: add_crawl_scheduling
Revises: enhance_update_intervals
Create Date: 2025-09-30 12:01:00.000000

Why: Combines two improvements for crawl scheduling:
1. Add last_crawled_at column to fix scheduling bug where editing website
   settings would reset the crawl schedule
2. Add database index for efficient crawl scheduling queries as system scales
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_crawl_scheduling'
down_revision = 'enhance_update_intervals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add last_crawled_at column and scheduling index.

    Why:
    - last_crawled_at separates crawl timing from record update timing
    - Index on (update_interval, updated_at) optimizes scheduling queries
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
    op.create_index(
        'idx_websites_crawl_scheduling',
        'websites',
        ['update_interval', 'updated_at']
    )


def downgrade() -> None:
    """Remove crawl scheduling enhancements."""
    # Remove index first
    op.drop_index('idx_websites_crawl_scheduling', table_name='websites')

    # Remove column
    op.drop_column('websites', 'last_crawled_at')
