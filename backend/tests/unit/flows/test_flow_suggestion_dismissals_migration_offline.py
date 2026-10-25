"""Database-free SQL generation of 202610251100 (`alembic upgrade --sql`)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from eneo.database.tables.flow_tables import FlowSuggestionDismissals

_TABLE = "flow_suggestion_dismissals"
_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/202610251100_add_flow_suggestion_dismissals.py"
)


def _sql(direction: str) -> str:
    spec = importlib.util.spec_from_file_location("flow_suggestion_dismissals", _PATH)
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


def test_upgrade_creates_the_table_keyed_by_tenant_flow_and_fingerprint() -> None:
    sql = _sql("upgrade")

    assert sql.index("SET LOCAL lock_timeout = '5s'") < sql.index("CREATE TABLE")
    assert f"CREATE TABLE {_TABLE} (" in sql
    assert (
        "CONSTRAINT fk_flow_suggestion_dismissals_flow_tenant FOREIGN KEY(flow_id, "
        "tenant_id) REFERENCES flows (id, tenant_id) ON DELETE CASCADE"
    ) in sql
    assert (
        "CONSTRAINT uq_flow_suggestion_dismissals_tenant_flow_fingerprint "
        "UNIQUE (tenant_id, flow_id, fingerprint)"
    ) in sql
    assert "FOREIGN KEY(dismissed_by) REFERENCES users (id) ON DELETE SET NULL" in sql
    assert "CHECK (fingerprint ~ '^[0-9a-f]{64}$')" in sql
    assert (
        f"CREATE INDEX ix_{_TABLE}_dismissed_by ON {_TABLE} (dismissed_by) "
        "WHERE dismissed_by IS NOT NULL"
    ) in sql


def test_downgrade_drops_the_table() -> None:
    sql = _sql("downgrade")

    assert f"DROP INDEX ix_{_TABLE}_dismissed_by" in sql
    assert f"DROP TABLE {_TABLE}" in sql
    assert "CREATE" not in sql


def test_the_table_declares_what_the_migration_creates() -> None:
    table = FlowSuggestionDismissals.__table__
    sql = _sql("upgrade")

    for column in table.columns:
        assert f"{column.name} " in sql, column.name
    assert {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None
    } >= {
        "fk_flow_suggestion_dismissals_flow_tenant",
        "uq_flow_suggestion_dismissals_tenant_flow_fingerprint",
        "ck_flow_suggestion_dismissals_fingerprint",
    }
    assert {index.name for index in table.indexes} == {f"ix_{_TABLE}_dismissed_by"}
