"""add crawler_engine field to websites

Revision ID: add_crawler_engine_001
Revises: f6ae7dc6c04f
Create Date: 2025-09-28 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_crawler_engine_001'
down_revision = '2f8e9a1b3c5d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type
    conn = op.get_bind()
    sa.Enum('SCRAPY', 'CRAWL4AI', name='crawlerengine').create(conn, checkfirst=True)

    # Add column as nullable first
    op.add_column(
        'websites',
        sa.Column(
            'crawler_engine',
            sa.Enum('SCRAPY', 'CRAWL4AI', name='crawlerengine'),
            nullable=True
        ),
    )

    # Set default value for existing records
    conn.execute(sa.text("UPDATE websites SET crawler_engine='SCRAPY' WHERE crawler_engine IS NULL"))

    # Make column non-nullable
    op.alter_column('websites', "crawler_engine", nullable=False)


def downgrade() -> None:
    op.drop_column('websites', 'crawler_engine')
    sa.Enum('SCRAPY', 'CRAWL4AI', name='crawlerengine').drop(op.get_bind(), checkfirst=True)