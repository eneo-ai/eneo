"""websites admin inventory indexes

Revision ID: 202605161430
Revises: 202605161200
Create Date: 2026-05-16 14:30:00.000000

Adds two composite indexes on `websites` to keep the new
`GET /api/v1/admin/crawler/websites` Webbplatser governance read
fast at scale:

- `idx_websites_tenant_last_crawled` (tenant_id, last_crawled_at)
  Covers the default `ORDER BY last_crawled_at DESC NULLS LAST` page
  load. Without it, a tenant with thousands of websites pays a full
  sequential scan + in-memory sort per page request.

- `idx_websites_tenant_update_interval` (tenant_id, update_interval)
  Covers the interval filter chip in the Webbplatser table. The
  cardinality of update_interval is low (NEVER, DAILY,
  EVERY_OTHER_DAY, WEEKLY) but tenant-scoped narrowing makes the
  index pay off when a tenant has hundreds of "Daily" websites.

Both indexes are created concurrently so production tenants with
large `websites` tables are not blocked on AccessExclusiveLock during
deploy. Mirrors the established crawler-subsystem migration pattern
in `202605142300_idx_active_crawl_lookup.py`.

If a deployment is interrupted while PostgreSQL is building these
concurrent indexes, operators should drop the invalid index
concurrently and rerun the migration. `IF NOT EXISTS` is kept for
normal deploy idempotency, not invalid-index repair.

Why no index on `lower(url)` here: ILIKE %term% requires pg_trgm GIN
to use an index, which is a heavier extension change. Deferred to v2
once telemetry shows search is hot.

Why no index on `(tenant_id, space_id)` or `(tenant_id, user_id)`:
those filters typically narrow to <100 rows per match, so the
seq-scan cost over a tenant's full website set stays small even at
10k rows. Adding the indexes preemptively is dead weight for the
common page-load and bulk-write paths.

Reversible: downgrade drops both indexes concurrently.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202605161430"
down_revision: Union[str, None] = "202605161200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LAST_CRAWLED_INDEX = "idx_websites_tenant_last_crawled"
UPDATE_INTERVAL_INDEX = "idx_websites_tenant_update_interval"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {LAST_CRAWLED_INDEX}
            ON websites (tenant_id, last_crawled_at)
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {UPDATE_INTERVAL_INDEX}
            ON websites (tenant_id, update_interval)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {UPDATE_INTERVAL_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {LAST_CRAWLED_INDEX}")
