"""add index for crawl scheduling performance

Revision ID: add_update_interval_index
Revises: enhance_update_intervals
Create Date: 2025-09-28 19:01:00.000000

Why: Optimize database queries for crawl scheduling as system scales.
Index on (update_interval, updated_at) enables fast selection of due websites.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_update_interval_index'
down_revision = 'enhance_update_intervals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add database index for efficient crawl scheduling queries.

    Why: Daily cron job needs fast queries to select websites due for crawling.
    Composite index on (update_interval, updated_at) optimizes the scheduling logic.
    """
    op.create_index(
        'idx_websites_crawl_scheduling',
        'websites',
        ['update_interval', 'updated_at']
    )


def downgrade() -> None:
    """Remove the crawl scheduling index."""
    op.drop_index('idx_websites_crawl_scheduling', table_name='websites')