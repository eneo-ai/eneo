"""Database-free SQL generation of 202610250900 (`alembic upgrade --sql`)."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations

_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/202610250900_flow_attempt_forwarding_facts.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("flow_forwarding_facts", _PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _sql(direction: str) -> str:
    migration = _migration()
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration, direction)()
    return output.getvalue()


def test_offline_upgrade_adds_one_nullable_jsonb_column() -> None:
    sql = _sql("upgrade")
    assert "SET LOCAL lock_timeout = '5s'" in sql
    assert (
        "ALTER TABLE flow_step_attempt_resolved_inputs "
        "ADD COLUMN forwarding_facts_jsonb JSONB"
    ) in sql
    assert "NOT NULL" not in sql
    assert "UPDATE" not in sql


def test_offline_downgrade_drops_the_column() -> None:
    sql = _sql("downgrade")
    assert (
        "ALTER TABLE flow_step_attempt_resolved_inputs "
        "DROP COLUMN forwarding_facts_jsonb"
    ) in sql
