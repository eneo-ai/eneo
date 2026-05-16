"""websites inventory trgm indexes

Revision ID: 202605170900
Revises: 202605161430
Create Date: 2026-05-17 09:00:00.000000

Adds two trigram GIN indexes on `websites` so the Webbplatser admin
tab's ILIKE `%term%` search hits an index instead of a sequential
scan. The search predicate at
`backend/src/intric/websites/domain/website_admin_repo.py:296-307`
is shaped to let pg_trgm GIN pick it up — no SQL rewrite required.

Why two separate indexes (url + name) rather than one combined:
- pg_trgm GIN doesn't compose across columns the way btree composite
  indexes do; the OR-clause search hits each column independently
- the planner can pick whichever index matches the highest-selectivity
  term in the user's query

Why no index on `users.email`:
- ownership of the user trigram surface lives elsewhere; the
  admin-inventory search OR-clauses email through the JOIN, but
  email trigram is a cross-cutting concern that belongs with the
  user-search migration (out of scope for this slice).

Why no `(tenant_id, ...)` composite:
- GIN indexes work on whichever trigram set matches; the planner
  intersects the trigram match against the tenant predicate
  separately. A composite GIN with btree_gin would add an extension
  + planner uncertainty that the audit-description precedent
  (`20251205_add_audit_description_trgm_index.py`) explicitly avoids.

`pg_trgm` is already enabled by that prior migration, so the
`CREATE EXTENSION IF NOT EXISTS` here is idempotent and free.

Why non-concurrent: this slice introduces only single-row Webbplatser
admin reads; the production websites table is small relative to
audit_logs, and a brief lock during deploy is acceptable. If the
operator confirms the table size grows large enough that the lock
becomes operationally relevant, swap to `CREATE INDEX
CONCURRENTLY` inside `autocommit_block` per the pattern in
`202605161430_websites_admin_inventory_indexes.py`.

Reversible: downgrade drops both indexes via IF EXISTS, leaving
pg_trgm enabled (it was enabled by a prior migration and is shared
with the audit-description index).
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
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {URL_INDEX}
        ON websites USING GIN (url gin_trgm_ops)
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {NAME_INDEX}
        ON websites USING GIN (name gin_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {NAME_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {URL_INDEX}")
