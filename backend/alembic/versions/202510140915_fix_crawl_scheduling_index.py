"""Fix crawl scheduling index to use last_crawled_at instead of updated_at

Revision ID: fix_crawl_scheduling_index
Revises: 6d9070b60c28
Create Date: 2025-10-14 09:15:00.000000

Why: The scheduler queries use last_crawled_at but the index was created on updated_at.
This fix ensures the database index matches the actual query pattern for optimal performance.

Query pattern: WHERE update_interval = X AND (last_crawled_at <= threshold OR last_crawled_at IS NULL)
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'fix_crawl_scheduling_index'
down_revision = '6d9070b60c28'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace the incorrect index with the correct one.

    Why: The scheduler service filters on (update_interval, last_crawled_at) not (update_interval, updated_at).
    This composite index enables efficient queries for finding websites due for crawling.
    """
    # Drop the incorrect index
    op.drop_index('idx_websites_crawl_scheduling', table_name='websites')

    # Create the correct composite index on (update_interval, last_crawled_at)
    # This supports queries: WHERE update_interval = X AND (last_crawled_at <= threshold OR last_crawled_at IS NULL)
    op.create_index(
        'idx_websites_crawl_scheduling',
        'websites',
        ['update_interval', 'last_crawled_at'],
        # postgresql_concurrently=True  # Uncomment for zero-downtime on large tables
    )


def downgrade() -> None:
    """Restore the original (incorrect) index for rollback compatibility."""
    op.drop_index('idx_websites_crawl_scheduling', table_name='websites')

    # Restore original (incorrect) index
    op.create_index(
        'idx_websites_crawl_scheduling',
        'websites',
        ['update_interval', 'updated_at'],
    )
