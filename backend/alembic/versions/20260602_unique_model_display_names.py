"""enforce unique active display names across model tables

Phase 3 of the model-table alignment (docs/plans/model-table-alignment).

A model's display name (`nickname`) is what users pick from in the chat model
selector and admin tables. Nothing stopped two *active* models in the same
tenant *and provider* from sharing one — producing rows that are impossible to
tell apart (e.g. several identical "gpt-5.1" entries). This migration:

  1. Renames existing active duplicates with a " (2)", " (3)" … suffix, keeping
     the oldest row untouched. No references are changed.
  2. Adds a partial unique index per table on
     (coalesce(tenant_id, sentinel), coalesce(provider_id, sentinel),
     lower(nickname)) restricted to *active* rows, so the collision cannot recur.

The scope includes `provider_id`: the same display name may intentionally repeat
across providers (e.g. a "gpt-5.1" sourced from two different providers in the
same tenant). Global models (tenant_id IS NULL) always have provider_id NULL, so
they collapse onto a single sentinel scope and stay unique per name as before.

"Active" = visible to end users = `deleted_at IS NULL AND is_deprecated = false`
(the same predicate the selector uses). Deprecated or soft-deleted rows kept for
historical references may freely reuse a name and never block a new one.

The same underlying model `name` may still repeat freely — it is the *display
name*, within one (tenant, provider), that must be distinct.

Revision ID: 20260602_unique_model_display_names
Revises: 20260601_align_model_tables
Create Date: 2026-06-02

"""
from collections import defaultdict
from itertools import groupby

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
# NB: revision id must fit alembic_version.version_num (varchar(32)); the
# longer descriptive name lives in the filename, not here.
revision = "20260602_unique_display_names"
down_revision = "20260601_align_model_tables"
branch_labels = None
depends_on = None

# Stand-in tenant_id for global (tenant_id IS NULL) rows so they share one
# uniqueness scope. Postgres treats NULLs as distinct in a unique index, so
# without this two global models could collide undetected.
SENTINEL = "00000000-0000-0000-0000-000000000000"

_TABLES = ("completion_models", "embedding_models", "transcription_models")


def _scope(value) -> str:
    return str(value) if value is not None else SENTINEL


def _dedupe(conn, table: str) -> None:
    rows = conn.execute(
        sa.text(
            f"""
            SELECT id, tenant_id, provider_id, nickname
            FROM {table}
            WHERE deleted_at IS NULL
              AND is_deprecated = false
              AND nickname IS NOT NULL
            ORDER BY COALESCE(tenant_id::text, :sentinel),
                     COALESCE(provider_id::text, :sentinel),
                     lower(nickname), created_at, id
            """
        ),
        {"sentinel": SENTINEL},
    ).fetchall()

    # Every active display name currently taken, per (tenant, provider) scope.
    # Renames update it so a suffixed name never lands on another active row.
    taken: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        taken[(_scope(row.tenant_id), _scope(row.provider_id))].add(
            row.nickname.lower()
        )

    def group_key(row):
        return (_scope(row.tenant_id), _scope(row.provider_id), row.nickname.lower())

    for (tenant_scope, provider_scope, _lower), group in groupby(rows, key=group_key):
        members = list(group)
        if len(members) <= 1:
            continue
        scope = (tenant_scope, provider_scope)
        # Keep the oldest (first by created_at) as-is; suffix the rest.
        for row in members[1:]:
            base = row.nickname
            n = 2
            while f"{base} ({n})".lower() in taken[scope]:
                n += 1
            new_name = f"{base} ({n})"
            taken[scope].add(new_name.lower())
            conn.execute(
                sa.text(f"UPDATE {table} SET nickname = :nn WHERE id = :id"),
                {"nn": new_name, "id": row.id},
            )


def upgrade() -> None:
    conn = op.get_bind()
    for table in _TABLES:
        _dedupe(conn, table)
        op.execute(
            f"""
            CREATE UNIQUE INDEX uq_{table}_active_nickname
            ON {table} (
                COALESCE(tenant_id, '{SENTINEL}'::uuid),
                COALESCE(provider_id, '{SENTINEL}'::uuid),
                lower(nickname)
            )
            WHERE deleted_at IS NULL
              AND is_deprecated = false
              AND nickname IS NOT NULL
            """
        )


def downgrade() -> None:
    # The suffix renames are left in place (no reliable inverse); only the
    # constraints are dropped.
    for table in _TABLES:
        op.execute(f"DROP INDEX IF EXISTS uq_{table}_active_nickname")
