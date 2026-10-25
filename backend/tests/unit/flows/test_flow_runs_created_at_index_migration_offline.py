"""Database-free SQL generation of 202610251000 (`alembic upgrade --sql`)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.flow_tables import FlowRuns

_INDEX = "ix_flow_runs_tenant_flow_created_at"
_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/202610251000_add_flow_runs_tenant_flow_created_at_index.py"
)


def _sql(direction: str) -> str:
    spec = importlib.util.spec_from_file_location("flow_runs_created_at_index", _PATH)
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


def test_upgrade_rebuilds_the_index_concurrently_within_the_lock_timeout() -> None:
    sql = _sql("upgrade")
    assert f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}" in sql
    assert (
        f"CREATE INDEX CONCURRENTLY {_INDEX} "
        "ON flow_runs (tenant_id, flow_id, created_at, id)"
    ) in sql
    assert sql.index("SET lock_timeout = '5s'") < sql.index("CREATE INDEX")
    assert sql.rindex("RESET lock_timeout") > sql.rindex("CREATE INDEX")


def test_downgrade_drops_the_index_concurrently() -> None:
    sql = _sql("downgrade")
    assert f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}" in sql
    assert "CREATE INDEX" not in sql
    assert "RESET lock_timeout" in sql


def test_the_table_declares_the_same_index() -> None:
    index = next(item for item in FlowRuns.__table__.indexes if item.name == _INDEX)
    assert [column.name for column in index.columns] == [
        "tenant_id",
        "flow_id",
        "created_at",
        "id",
    ]
