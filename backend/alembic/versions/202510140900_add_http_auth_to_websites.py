"""add http auth to websites

Revision ID: add_http_auth_to_websites
Revises: add_website_crawl_scheduling
Create Date: 2025-10-14 09:00:00.000000

Why: Add HTTP Basic Authentication support for websites requiring login credentials.

Schema Design:
1. Separate columns (not JSONB) for better indexing and query performance
2. All nullable - auth is optional feature
3. encrypted_auth_password stores base64-encoded Fernet ciphertext
4. auth_domain extracted from URL for Scrapy security requirements
5. No breaking changes - existing websites continue working
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_http_auth_to_websites'
down_revision = 'add_website_crawl_scheduling'
branch_labels = None
depends_on = None


def upgrade():
    """Add HTTP Basic Auth support to websites table.

    Schema Design Rationale:
    - Separate columns for better query performance vs JSONB
    - All nullable to maintain backward compatibility
    - No default values (NULL = no auth configured)
    """
    # Add columns for HTTP auth
    op.add_column('websites', sa.Column(
        'http_auth_username',
        sa.String(),
        nullable=True,
        comment='HTTP Basic Auth username (plaintext)'
    ))

    op.add_column('websites', sa.Column(
        'encrypted_auth_password',
        sa.String(),
        nullable=True,
        comment='HTTP Basic Auth password (Fernet encrypted, base64 encoded)'
    ))

    op.add_column('websites', sa.Column(
        'http_auth_domain',
        sa.String(),
        nullable=True,
        comment='Domain for HTTP auth (extracted from URL, required by Scrapy HttpAuthMiddleware)'
    ))

    # Add index for filtering websites with auth (optional, for analytics)
    # Only index where auth is actually configured to save space
    op.execute("""
        CREATE INDEX ix_websites_has_http_auth
        ON websites(tenant_id, http_auth_username)
        WHERE http_auth_username IS NOT NULL
    """)


def downgrade():
    """Remove HTTP auth columns (safe - data loss acceptable for downgrade)."""
    op.drop_index('ix_websites_has_http_auth', table_name='websites', postgresql_where=sa.text('http_auth_username IS NOT NULL'))
    op.drop_column('websites', 'http_auth_domain')
    op.drop_column('websites', 'encrypted_auth_password')
    op.drop_column('websites', 'http_auth_username')
