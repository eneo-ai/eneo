"""Add HTTP Basic Auth, automated scheduling, circuit breaker, and file hashing

Revision ID: add_http_auth_and_scheduling
Revises: 2b3c4d5e6f7a
Create Date: 2025-10-14 00:00:00.000000

Consolidated Migration - Adds Four Major Features:

1. HTTP Basic Authentication
   - Secure credential storage with Fernet encryption
   - Domain-locked credentials for security
   - Support for protected websites

2. Automated Crawl Scheduling
   - DAILY, EVERY_OTHER_DAY, WEEKLY, NEVER intervals
   - Independent last_crawled_at tracking
   - Optimized database indexes

3. Circuit Breaker (Failure Resilience)
   - Exponential backoff: 1h → 2h → 4h → 8h → 16h → 24h
   - Auto-disable after 10 consecutive failures
   - Automatic recovery on success

4. File Content Hashing
   - SHA-256 hash checking for files (PDFs, docs)
   - 100% skip rate for unchanged files
   - Major token savings on document-heavy sites

Tables Modified:
- websites: +6 columns, +3 indexes
- info_blobs: +1 column, +1 index
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = "add_http_auth_and_scheduling"
down_revision = "2b3c4d5e6f7a"  # Last stable migration before this feature branch
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add HTTP auth, scheduling, circuit breaker, and file hashing features."""

    # ========================================
    # 1. AUTOMATED CRAWL SCHEDULING
    # ========================================

    # Add last_crawled_at column for independent crawl tracking
    op.add_column(
        "websites",
        sa.Column(
            "last_crawled_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="When website was last crawled (independent of record updates)",
        ),
    )

    # Backfill existing websites: set last_crawled_at = updated_at for crawled websites
    op.execute(
        """
        UPDATE websites w
        SET last_crawled_at = w.updated_at
        WHERE EXISTS (
            SELECT 1 FROM crawl_runs cr WHERE cr.website_id = w.id
        )
    """
    )

    # Create scheduling index (using last_crawled_at, not updated_at)
    # Query pattern: WHERE update_interval = X AND (last_crawled_at <= threshold OR IS NULL)
    op.create_index(
        "idx_websites_crawl_scheduling",
        "websites",
        ["update_interval", "last_crawled_at"],
    )

    # ========================================
    # 2. HTTP BASIC AUTHENTICATION
    # ========================================

    # Add HTTP auth columns (all nullable - optional feature)
    op.add_column(
        "websites",
        sa.Column(
            "http_auth_username",
            sa.String(),
            nullable=True,
            comment="HTTP Basic Auth username",
        ),
    )

    op.add_column(
        "websites",
        sa.Column(
            "encrypted_auth_password",
            sa.String(),
            nullable=True,
            comment="Fernet-encrypted password (base64 encoded)",
        ),
    )

    op.add_column(
        "websites",
        sa.Column(
            "http_auth_domain",
            sa.String(),
            nullable=True,
            comment="Domain for HTTP auth (from URL netloc, required by Scrapy)",
        ),
    )

    # Add partial index for websites with auth configured
    op.execute(
        """
        CREATE INDEX ix_websites_has_http_auth
        ON websites(tenant_id, http_auth_username)
        WHERE http_auth_username IS NOT NULL
    """
    )

    # ========================================
    # 3. CIRCUIT BREAKER (FAILURE HANDLING)
    # ========================================

    # Add failure tracking fields
    op.add_column(
        "websites",
        sa.Column(
            "consecutive_failures",
            sa.Integer,
            nullable=False,
            server_default="0",
            comment="Number of consecutive crawl failures (resets on success)",
        ),
    )

    op.add_column(
        "websites",
        sa.Column(
            "next_retry_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="When to retry after failures (NULL = retry now)",
        ),
    )

    # Add partial index for circuit breaker queries
    op.create_index(
        "idx_websites_circuit_breaker",
        "websites",
        ["next_retry_at"],
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )

    # ========================================
    # 4. FILE CONTENT HASHING
    # ========================================

    # Add content_hash column to info_blobs
    op.add_column(
        "info_blobs",
        sa.Column(
            "content_hash",
            sa.LargeBinary(length=32),
            nullable=True,
            comment="SHA-256 hash for file change detection (files only)",
        ),
    )

    # Add composite index for fast file hash lookups
    op.create_index(
        "idx_info_blobs_website_title_lookup",
        "info_blobs",
        ["website_id", "title"],
    )


def downgrade() -> None:
    """Remove all added features (safe for rollback)."""

    # Remove file hashing
    op.drop_index("idx_info_blobs_website_title_lookup", table_name="info_blobs")
    op.drop_column("info_blobs", "content_hash")

    # Remove circuit breaker
    op.drop_index(
        "idx_websites_circuit_breaker",
        table_name="websites",
        postgresql_where=sa.text("next_retry_at IS NOT NULL"),
    )
    op.drop_column("websites", "next_retry_at")
    op.drop_column("websites", "consecutive_failures")

    # Remove HTTP auth
    op.drop_index(
        "ix_websites_has_http_auth",
        table_name="websites",
        postgresql_where=sa.text("http_auth_username IS NOT NULL"),
    )
    op.drop_column("websites", "http_auth_domain")
    op.drop_column("websites", "encrypted_auth_password")
    op.drop_column("websites", "http_auth_username")

    # Remove scheduling
    op.drop_index("idx_websites_crawl_scheduling", table_name="websites")
    op.drop_column("websites", "last_crawled_at")
