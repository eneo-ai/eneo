"""websites inventory trgm indexes

Revision ID: 202605170900
Revises: 202605161430
Create Date: 2026-05-17 09:00:00.000000

Adds two trigram GIN indexes on `websites` so the Webbplatser admin
tab's ILIKE `%term%` search picks up a GIN index instead of doing a
sequential scan on `url` and `name`. The search predicate at
`backend/src/intric/websites/domain/website_admin_repo.py:296-307`
ORs `websites.url`, `websites.name`, and `users.email`. This
migration only indexes the two `websites` columns — the email leg
is a cross-cutting concern owned by the user-search surface and is
deferred to a follow-up; until it lands, the planner may fall back
to a seq-scan on the email arm of the OR clause.

Why two separate indexes (url + name) rather than one combined:
- pg_trgm GIN doesn't compose across columns the way btree
  composite indexes do; the planner can BitmapOr a separate GIN scan
  per column.

Why no `(tenant_id, ...)` composite:
- GIN indexes work on whichever trigram set matches; the planner
  intersects the trigram match against the tenant predicate
  separately. A composite GIN with btree_gin would add an extension
  + planner uncertainty that the audit-description precedent
  (`20251205_add_audit_description_trgm_index.py`) explicitly
  avoids.

`pg_trgm` is already enabled by that prior migration, so the
`CREATE EXTENSION IF NOT EXISTS` here is idempotent and free.

Why CONCURRENTLY:
- The `websites` table is production-shared and tenant-multiplexed.
  A non-concurrent CREATE INDEX would hold an
  AccessExclusiveLock for the build duration, blocking every
  `INSERT INTO websites` (user-facing flow) during deploy.
- Mirrors the established precedent in
  `202605161430_websites_admin_inventory_indexes.py:22-25,58-70`
  which already takes the autocommit-block + concurrent-create path
  on the same table.
- Codex pre-merge review (gpt-5.5/high) flagged the previous
  non-concurrent shape as the only HIGH finding on this slice; this
  edit lands the AB recommendation directly.

If a deployment is interrupted while PostgreSQL is building these
concurrent indexes, operators should `DROP INDEX CONCURRENTLY IF
EXISTS <name>` and rerun the migration; `IF NOT EXISTS` keeps
normal deploy idempotency.

Reversible: downgrade drops both indexes concurrently via IF EXISTS,
leaving pg_trgm enabled (shared with the audit-description index
and the crawler search predicate).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "202605170900"
down_revision: Union[str, None] = "202605161430"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

URL_INDEX = "idx_websites_url_trgm"
NAME_INDEX = "idx_websites_name_trgm"


def upgrade() -> None:
    # pg_trgm extension is already enabled by the audit-description
    # migration; keep the idempotent CREATE here so a fresh-database
    # deploy that runs migrations out of order still picks it up.
    # The CREATE EXTENSION can run inside the default transaction;
    # only the CONCURRENTLY index builds need autocommit_block().
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {URL_INDEX}
            ON websites USING GIN (url gin_trgm_ops)
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {NAME_INDEX}
            ON websites USING GIN (name gin_trgm_ops)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {NAME_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {URL_INDEX}")
