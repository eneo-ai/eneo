"""enhance update intervals with daily and every other day options

Revision ID: enhance_update_intervals
Revises: add_crawler_engine_001
Create Date: 2025-09-28 19:00:00.000000

Why: Add flexible crawl scheduling options while maintaining backwards compatibility.
Enables daily and every-other-day crawling for both Scrapy and Crawl4AI engines.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'enhance_update_intervals'
down_revision = 'add_crawler_engine_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add new interval values - update_interval is stored as string, not enum.

    Why: update_interval is stored as VARCHAR, not PostgreSQL enum type.
    No database changes needed - new values work immediately.
    Migration exists for consistency and future enum type migration if needed.
    """
    # No database changes needed - update_interval is stored as string
    # New enum values ('daily', 'every_other_day') work immediately
    pass


def downgrade() -> None:
    """Remove new interval values - update existing websites to safe values.

    Why: Convert any websites using new intervals back to supported values.
    Since update_interval is stored as string, just update the data.
    """
    # Convert new interval values back to existing ones for rollback safety
    op.execute("""
        UPDATE websites
        SET update_interval = 'never'
        WHERE update_interval IN ('daily', 'every_other_day')
    """)