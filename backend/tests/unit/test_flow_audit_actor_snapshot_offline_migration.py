"""Revision 202610021000 renders as offline SQL (`alembic upgrade --sql`) without a database."""

from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config


def _offline_sql(revision_range: str, *, downgrade: bool = False) -> str:
    backend = Path(__file__).resolve().parents[2]
    output = io.StringIO()
    config = Config(str(backend / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(backend / "alembic"))
    config.set_main_option("sqlalchemy.url", "postgresql://offline@localhost/offline")
    if downgrade:
        command.downgrade(config, revision_range, sql=True)
    else:
        command.upgrade(config, revision_range, sql=True)
    return output.getvalue()


def test_upgrade_renders_the_column_and_both_concurrent_actor_indexes() -> None:
    sql = _offline_sql("202609291100:202610021000")

    assert (
        "ALTER TABLE flow_run_audit_outbox ADD COLUMN IF NOT EXISTS actor_snapshot JSONB"
        in sql
    )
    for column in ("actor_id", "actor_api_key_id"):
        assert (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_flow_run_audit_outbox_{column} "
            f"ON flow_run_audit_outbox ({column}) WHERE {column} IS NOT NULL"
        ) in sql
    assert "pg_index" not in sql


def test_downgrade_renders_the_index_and_column_drops() -> None:
    sql = _offline_sql("202610021000:202609291100", downgrade=True)

    for column in ("actor_id", "actor_api_key_id"):
        assert (
            f"DROP INDEX CONCURRENTLY IF EXISTS ix_flow_run_audit_outbox_{column}"
            in sql
        )
    assert "ALTER TABLE flow_run_audit_outbox DROP COLUMN actor_snapshot" in sql
