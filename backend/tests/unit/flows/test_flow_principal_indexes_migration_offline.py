"""Database-free SQL generation of 202610021030 (`alembic upgrade --sql`).

Offline mode has no connection, so the revision must not inspect pg_index; it emits
the static concurrent statements for every new index.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

NEW_INDEX_COUNT = 23
_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/202610021030_add_flow_gallring_and_principal_indexes.py"
)


def _sql(direction: str) -> str:
    spec = importlib.util.spec_from_file_location("flow_principal_indexes", _PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration, direction)()
    return output.getvalue()


def test_offline_upgrade_emits_every_concurrent_index_without_reading_pg_index() -> (
    None
):
    sql = _sql("upgrade")
    assert sql.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == NEW_INDEX_COUNT
    assert "pg_index" not in sql
    assert "DROP INDEX" not in sql
    assert "SET lock_timeout = '5s'" in sql
    assert sql.rindex("RESET lock_timeout") > sql.rindex("CREATE INDEX")
    assert (
        "ON flow_provider_calls (resolved_inputs_attempt_id) "
        "WHERE resolved_inputs_attempt_id IS NOT NULL"
    ) in sql
    assert "ON flow_runtime_uploaded_files (created_at, file_id)" in sql


def test_offline_downgrade_drops_every_index_concurrently() -> None:
    sql = _sql("downgrade")
    assert sql.count("DROP INDEX CONCURRENTLY IF EXISTS") == NEW_INDEX_COUNT
    assert "RESET lock_timeout" in sql
