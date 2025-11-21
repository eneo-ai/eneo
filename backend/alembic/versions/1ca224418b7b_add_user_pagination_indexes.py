"""add_user_pagination_indexes

Adds database indexes for admin users pagination and fuzzy text search optimization.

Performance improvement: O(n) sequential scans → O(log n + k) indexed queries.

Indexes created:
- Composite B-tree indexes for tenant isolation + pagination/sorting
- GIN trigram indexes for fuzzy email/username search with case-insensitive matching
- Partial indexes exclude soft-deleted users for efficiency

All indexes created with CONCURRENTLY option for zero-downtime deployment.

Revision ID: 1ca224418b7b
Revises: c24c8d895bcd
Create Date: 2025-11-04 19:01:14.713317
"""

from alembic import op


# revision identifiers, used by Alembic
revision = '1ca224418b7b'
down_revision = 'c24c8d895bcd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add pg_trgm extension and performance indexes for user pagination/search.

    Time complexity improvement:
    - Pagination queries: O(n) → O(log n + page_size)
    - Search queries: O(n) → O(log n + matches)

    IMPORTANT: All indexes created with CONCURRENTLY to prevent table locking.
    Uses autocommit_block() as CONCURRENTLY operations cannot run in transactions.
    """

    # Enable required extensions for advanced indexing
    # pg_trgm: Trigram similarity search for fuzzy text matching
    # btree_gin: Allows GIN indexes on regular columns (for tenant_id) + trigram columns
    # Idempotent: IF NOT EXISTS prevents errors if already installed
    # Can run in transaction (do not require CONCURRENTLY)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin;")

    # All CONCURRENTLY operations must run outside transaction
    # Using Alembic's canonical autocommit_block() pattern
    with op.get_context().autocommit_block():
        # Composite B-tree index: Tenant isolation + stable pagination sort
        # Query: WHERE tenant_id = X AND deleted_at IS NULL ORDER BY created_at DESC, id DESC LIMIT Y OFFSET Z
        # CRITICAL: id DESC provides stable tie-breaker for rows with identical created_at
        # Without this, pagination can show duplicates/skips when new users are created
        # Complexity: O(log n + offset + page_size)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_tenant_created_id
            ON users (tenant_id, created_at DESC, id DESC)
            WHERE deleted_at IS NULL;
        """)

        # Composite B-tree index: Tenant isolation + sorting by email
        # Query: WHERE tenant_id = X AND deleted_at IS NULL ORDER BY email ASC/DESC
        # Also supports: WHERE tenant_id = X AND email = 'specific@example.com'
        # Complexity: O(log n + k)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_tenant_email
            ON users (tenant_id, email)
            WHERE deleted_at IS NULL;
        """)

        # Composite B-tree index: Tenant isolation + sorting by username
        # Query: WHERE tenant_id = X AND deleted_at IS NULL ORDER BY username ASC/DESC
        # Complexity: O(log n + k)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_tenant_username
            ON users (tenant_id, username)
            WHERE deleted_at IS NULL;
        """)

        # GIN trigram index: Tenant-aware fuzzy email search (uses btree_gin extension)
        # Query: WHERE tenant_id = X AND deleted_at IS NULL AND lower(email) ILIKE '%search%'
        # CRITICAL: Includes tenant_id to avoid cross-tenant scans in multi-tenant queries
        # btree_gin allows combining exact match (tenant_id) + trigram search (email) in one index
        # Complexity: O(log n + matches) where matches = rows in tenant with similar email
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_tenant_email_trgm
            ON users USING gin (tenant_id, lower(email) gin_trgm_ops)
            WHERE deleted_at IS NULL;
        """)

        # GIN trigram index: Tenant-aware fuzzy username search
        # Query: WHERE tenant_id = X AND deleted_at IS NULL AND lower(username) ILIKE '%search%'
        # CRITICAL: Includes tenant_id for multi-tenant efficiency
        # Complexity: O(log n + matches)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_tenant_username_trgm
            ON users USING gin (tenant_id, lower(username) gin_trgm_ops)
            WHERE deleted_at IS NULL;
        """)


def downgrade() -> None:
    """
    Remove pagination indexes (rollback strategy).

    IMPORTANT: Use CONCURRENTLY to prevent table locking during rollback.
    Uses autocommit_block() as CONCURRENTLY operations cannot run in transactions.
    Note: pg_trgm extension is NOT dropped (may be used by other features).
    """

    # All CONCURRENTLY operations must run outside transaction
    with op.get_context().autocommit_block():
        # Drop indexes in reverse order (matching updated index names)
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_users_tenant_username_trgm;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_users_tenant_email_trgm;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_users_tenant_username;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_users_tenant_email;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_users_tenant_created_id;")

    # Do NOT drop pg_trgm extension (may be used elsewhere)
    # op.execute("DROP EXTENSION IF EXISTS pg_trgm;")  # COMMENTED OUT INTENTIONALLY